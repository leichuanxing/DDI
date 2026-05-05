from datetime import timedelta
import ipaddress
from pathlib import Path
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.html import format_html
from rest_framework.decorators import api_view
from rest_framework import viewsets
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from common.responses import success_response
from ipam.models import AddressSpace, IPAddress, IPAddressHistory, Subnet
from ipam.services import IPAMService
from dns.models import DNSProviderConfig, DNSZone, DNSRecord, DNSChangeLog
from dhcp.models import DHCPOption, DHCPPool, DHCPProviderConfig, DHCPLease, DHCPReservation, DHCPSubnet
from tasks.models import SystemTask, TaskLog
from audit.models import AuditLog
from accounts.models import LoginLog, Permission, Role
from dns.services import DNSService
from dhcp.services import DHCPService
from .models import SystemConfig, ServiceHealthCheck
from .serializers import SystemConfigSerializer, ServiceHealthCheckSerializer
from .services import HealthService

STATUS_LABELS = {
    'available': '可用', 'used': '已使用', 'reserved': '预留', 'dhcp_dynamic': 'DHCP 动态分配',
    'dhcp_reserved': 'DHCP 固定分配', 'disabled': '禁用', 'enabled': '启用', 'planned': '规划中',
    'pending': '等待执行', 'running': '执行中', 'success': '成功', 'failed': '失败', 'canceled': '已取消',
    'normal': '正常', 'abnormal': '异常', 'unknown': '未知', 'active': '活跃',
}


def badge(status, label=None):
    status = status or 'unknown'
    return format_html('<span class="status-badge status-{}">{}</span>', status, label or STATUS_LABELS.get(status, status))


def progress(value):
    value = max(0, min(100, int(value or 0)))
    cls = 'danger' if value >= 90 else 'warn' if value >= 70 else ''
    return format_html('<div style="display:grid;gap:5px"><div class="progress {}"><span style="width:{}%"></span></div><small>{}%</small></div>', cls, value, value)


def pool_capacity(pool):
    try:
        start = ipaddress.ip_address(pool.pool_start)
        end = ipaddress.ip_address(pool.pool_end)
    except ValueError:
        return 0
    return int(end) - int(start) + 1


def pool_used_count(pool):
    try:
        start = ipaddress.ip_address(pool.pool_start)
        end = ipaddress.ip_address(pool.pool_end)
    except ValueError:
        return 0
    used = 0
    for lease in DHCPLease.objects.filter(subnet_id=pool.dhcp_subnet.subnet_id, state='active'):
        ip_value = ipaddress.ip_address(lease.ip_address)
        if start <= ip_value <= end:
            used += 1
    for reservation in pool.dhcp_subnet.reservations.filter(status='enabled'):
        ip_value = ipaddress.ip_address(reservation.ip_address)
        if start <= ip_value <= end:
            used += 1
    return used


def cell(html, truncate=False):
    return {'html': html if html not in (None, '') else '-', 'truncate': truncate}


def status_label(value):
    return STATUS_LABELS.get(value, value or '未知')


def component_health(name):
    return ServiceHealthCheck.objects.filter(service_name=name).first()


def dns_config_complete(obj):
    return bool(obj.api_url and obj.api_port and obj.api_key and obj.server_id)


def dhcp_config_complete(obj):
    if not (obj.api_url and obj.api_port and obj.service_type):
        return False
    if obj.auth_enabled and not (obj.username and obj.password):
        return False
    return True


def component_association_badge(api_url, expected_host):
    if expected_host in (api_url or ''):
        return badge('enabled', f'已关联 {expected_host}')
    return badge('warning', '非默认容器')


def component_health_cells(health):
    if not health:
        return [
            cell(badge('unknown', '未知')),
            cell('-'),
            cell('-'),
        ]
    return [
        cell(badge(health.status, status_label(health.status))),
        cell(health.checked_at.strftime('%Y-%m-%d %H:%M') if health.checked_at else '-'),
        cell(health.error_message or '-', True),
    ]


DNS_RECURSION_KEY = 'dns_recursion'
DNS_RECURSION_DEFAULT = {
    'enabled': True,
    'forward_zones': 'devnets.net',
    'upstream_dns_1': '223.5.5.5',
    'upstream_dns_2': '119.29.29.29',
}


def dns_recursion_config():
    obj, _ = SystemConfig.objects.get_or_create(
        key=DNS_RECURSION_KEY,
        defaults={'value': DNS_RECURSION_DEFAULT, 'description': 'PowerDNS 前置递归转发配置'},
    )
    value = obj.value or {}
    merged = {**DNS_RECURSION_DEFAULT, **value}
    if obj.value != merged:
        obj.value = merged
        obj.save(update_fields=['value', 'updated_at'])
    return merged


def normalize_forward_zones(value):
    zones = []
    for item in re.split(r'[\s,，]+', value or ''):
        zone = item.strip().strip('.').lower()
        if zone and re.fullmatch(r'[a-z0-9-]+(\.[a-z0-9-]+)*', zone):
            zones.append(zone)
    return ','.join(dict.fromkeys(zones)) or DNS_RECURSION_DEFAULT['forward_zones']


def normalize_upstream_dns(value):
    value = (value or '').strip()
    if value and re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
        return value
    return ''


def save_dns_recursion_runtime(config):
    runtime_dir = Path(settings.BASE_DIR) / 'docker' / 'pdns' / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_file = runtime_dir / 'recursion.env'
    lines = [
        f"RECURSION_ENABLED={'1' if config.get('enabled') else '0'}",
        f"PDNS_FORWARD_ZONES={config.get('forward_zones') or ''}",
        f"PUBLIC_DNS_1={config.get('upstream_dns_1') or ''}",
        f"PUBLIC_DNS_2={config.get('upstream_dns_2') or ''}",
    ]
    tmp_file = runtime_file.with_suffix('.env.tmp')
    tmp_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    tmp_file.replace(runtime_file)


def register_authoritative_zone(zone_name):
    zone = (zone_name or '').strip().lower().strip('.')
    if not zone:
        return
    config = dns_recursion_config()
    zones = normalize_forward_zones(config.get('forward_zones'))
    zone_list = [item for item in zones.split(',') if item]
    if zone not in zone_list:
        zone_list.append(zone)
        config['forward_zones'] = ','.join(zone_list)
        SystemConfig.objects.update_or_create(
            key=DNS_RECURSION_KEY,
            defaults={'value': config, 'description': 'PowerDNS 前置递归转发配置'},
        )
        save_dns_recursion_runtime(config)


def normalize_dns_zone_name(value):
    name = (value or '').strip().lower().strip('.')
    if not name:
        return ''
    return f'{name}.'


def ensure_dns_zone(name, user=None, request=None):
    zone_name = normalize_dns_zone_name(name)
    zone, created = DNSZone.objects.get_or_create(name=zone_name, defaults={'kind': 'Native', 'status': 'enabled'})
    register_authoritative_zone(zone.name)
    if not created and not zone.synced_at:
        remote = DNSService.client().get_zone(DNSService.canonical_zone_name(zone.name))
        if remote.get('success'):
            zone.synced_at = timezone.now()
            zone.save(update_fields=['synced_at', 'updated_at'])
            return zone
    if created or not zone.synced_at:
        DNSService.push_zone(zone, user=user, request=request)
    return zone


def reverse_zone_for_ipv4(ip_value):
    ip = ipaddress.ip_address((ip_value or '').strip())
    if ip.version != 4:
        raise ValueError('当前反向解析页面仅支持 IPv4 PTR')
    octets = str(ip).split('.')
    return f'{octets[2]}.{octets[1]}.{octets[0]}.in-addr.arpa.', octets[3]


def upsert_dns_record(zone, name, record_type, content, ttl=3600, priority=None, comment='', user=None, request=None):
    record, _ = DNSRecord.objects.update_or_create(
        zone=zone,
        name=(name or '').strip(),
        record_type=record_type,
        content=(content or '').strip(),
        defaults={
            'ttl': int(ttl or 3600),
            'priority': priority or None,
            'disabled': False,
            'comment': comment or '',
        },
    )
    result = DNSService.push_record(record, user=user, request=request)
    return record, result


def latest_dns_tasks():
    return SystemTask.objects.filter(task_type__in=['dns_zone_push', 'dns_record_push', 'dns_record_sync']).order_by('-created_at')[:8]


def dns_record_result_message(result, success_text):
    if result.get('success'):
        return success_text
    return result.get('message') or 'PowerDNS 下发失败'


def delete_dns_record(record):
    return DNSService.client().delete_record(
        DNSService.canonical_zone_name(record.zone.name),
        DNSService.canonical_record_name(record.name, record.zone.name),
        record.record_type,
    )


def save_dns_record_from_form(request, instance=None):
    direction = request.POST.get('direction') or ('reverse' if instance and instance.record_type == 'PTR' else 'forward')
    ttl = int(request.POST.get('ttl') or 3600)
    if direction == 'reverse':
        target = (request.POST.get('target') or request.POST.get('content') or '').strip()
        ip_value = (request.POST.get('ip_address') or '').strip()
        if ip_value:
            zone_name, record_name = reverse_zone_for_ipv4(ip_value)
            zone = ensure_dns_zone(zone_name, user=request.user, request=request)
        elif instance:
            zone = instance.zone
            record_name = instance.name
        else:
            raise ValueError('新增反向解析时必须填写 IP 地址')
        record = instance or DNSRecord()
        record.zone = zone
        record.name = record_name
        record.record_type = 'PTR'
        record.content = target
        record.ttl = ttl
        record.priority = None
        record.disabled = request.POST.get('disabled') == 'on'
        record.comment = request.POST.get('comment') or ''
        record.synced_at = None
        record.save()
        return record

    zone = DNSZone.objects.filter(pk=request.POST.get('zone_id')).first()
    zone_name = request.POST.get('zone_name') or (zone.name if zone else '')
    zone = ensure_dns_zone(zone_name, user=request.user, request=request)
    record_type = request.POST.get('record_type') or 'A'
    if record_type == 'PTR':
        raise ValueError('PTR 请使用反向解析模式')
    record = instance or DNSRecord()
    record.zone = zone
    record.name = request.POST.get('name') or '@'
    record.record_type = record_type
    record.content = request.POST.get('content') or ''
    record.ttl = ttl
    record.priority = int(request.POST.get('priority') or 10) if record_type == 'MX' else None
    record.disabled = request.POST.get('disabled') == 'on'
    record.comment = request.POST.get('comment') or ''
    record.synced_at = None
    record.save()
    return record


def dns_record_form_context(request, instance=None):
    direction = request.POST.get('direction') or request.GET.get('direction') or ('reverse' if instance and instance.record_type == 'PTR' else 'forward')
    return {
        'section_title': 'DNS 管理',
        'page_title': '编辑DNS记录' if instance else '新增DNS记录',
        'page_description': '统一新增正向解析记录和反向 PTR 记录。',
        'form_title': '编辑DNS记录' if instance else '新增DNS记录',
        'active_section': 'dns',
        'active_menu': 'records',
        'back_url': '/ui/dns/records/',
        'record': instance,
        'direction': direction,
        'zones': DNSZone.objects.filter(status='enabled').order_by('name'),
        'forward_record_types': ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA'],
    }


API_BASE = {
    ('ipam', 'address-spaces'): '/api/ipam/address-spaces/',
    ('ipam', 'subnets'): '/api/ipam/subnets/',
    ('ipam', 'ip-addresses'): '/api/ipam/ip-addresses/',
    ('ipam', 'histories'): '/api/ipam/histories/',
    ('dns', 'zones'): '/api/dns/zones/',
    ('dns', 'service'): '/api/dns/config/',
    ('dns', 'records'): '/api/dns/records/',
    ('dns', 'change-logs'): '/api/dns/change-logs/',
    ('dhcp', 'subnets'): '/api/dhcp/subnets/',
    ('dhcp', 'service'): '/api/dhcp/config/',
    ('dhcp', 'pools'): '/api/dhcp/pools/',
    ('dhcp', 'reservations'): '/api/dhcp/reservations/',
    ('dhcp', 'options'): '/api/dhcp/options/',
    ('dhcp', 'leases'): '/api/dhcp/leases/',
    ('dhcp', 'lease-history'): '/api/dhcp/leases/',
    ('tasks', 'list'): '/api/tasks/',
    ('tasks', 'failed'): '/api/tasks/',
    ('audit', 'operations'): '/api/audit-logs/',
    ('audit', 'login'): '/api/login-logs/',
    ('system', 'users'): '/api/users/',
    ('system', 'roles'): '/api/roles/',
    ('system', 'permissions'): '/api/permissions/',
    ('system', 'configs'): '/api/health/configs/',
}


EXPORT_URLS = {
    ('ipam', 'subnets'): '/api/ipam/subnets/export-excel/',
    ('ipam', 'ip-addresses'): '/api/ipam/ip-addresses/export-excel/',
    ('audit', 'operations'): '/api/audit-logs/export/',
}

IMPORT_URLS = {
    ('ipam', 'subnets'): '/api/ipam/subnets/import-excel/',
    ('ipam', 'ip-addresses'): '/api/ipam/ip-addresses/import-excel/',
}

FORM_FIELDS = {
    ('ipam', 'address-spaces'): ['name', 'code', 'description'],
    ('ipam', 'subnets'): ['address_space', 'cidr', 'gateway', 'vlan_id', 'vlan_name', 'location', 'usage_type', 'description', 'status'],
    ('ipam', 'ip-addresses'): ['subnet', 'ip_address', 'hostname', 'mac_address', 'status', 'usage_type', 'owner', 'department', 'description', 'dns_record', 'dhcp_reservation'],
    ('dns', 'service'): ['api_url', 'api_port', 'api_key', 'server_id', 'timeout', 'use_ssl', 'health_check_enabled'],
    ('dns', 'zones'): ['name', 'kind', 'dnssec', 'soa_edit_api', 'api_rectify', 'description', 'status'],
    ('dns', 'records'): ['zone', 'name', 'record_type', 'content', 'ttl', 'priority', 'disabled', 'comment'],
    ('dhcp', 'service'): ['api_url', 'api_port', 'service_type', 'timeout', 'auth_enabled', 'username', 'password', 'health_check_enabled'],
    ('dhcp', 'subnets'): ['ipam_subnet', 'subnet', 'subnet_id', 'interface', 'relay_ip', 'gateway', 'dns_servers', 'domain_name', 'lease_time', 'valid_lifetime', 'renew_timer', 'rebind_timer', 'description', 'status'],
    ('dhcp', 'pools'): ['dhcp_subnet', 'pool_start', 'pool_end', 'description', 'status'],
    ('dhcp', 'reservations'): ['dhcp_subnet', 'ip_address', 'mac_address', 'hostname', 'client_id', 'description', 'status'],
    ('dhcp', 'options'): ['scope_type', 'scope_id', 'option_code', 'option_name', 'option_value', 'description'],
    ('system', 'users'): ['username', 'real_name', 'email', 'mobile', 'is_active', 'is_superuser'],
    ('system', 'roles'): ['name', 'code', 'description'],
    ('system', 'permissions'): ['module', 'action', 'code', 'description'],
    ('system', 'configs'): ['key', 'value', 'description'],
}


def form_model_meta(section, page):
    meta = PAGE_META.get((section, page))
    fields = FORM_FIELDS.get((section, page))
    if not meta or not fields:
        return None, None
    return meta, fields


def ensure_component_config(section, page):
    if (section, page) == ('dns', 'service'):
        return DNSService.reset_default_config()
    if (section, page) == ('dhcp', 'service'):
        return DHCPService.ensure_config()
    return None


def row_urls(section, page, obj_id):
    base = API_BASE.get((section, page))
    if (section, page) in {('dns', 'service'), ('dhcp', 'service')}:
        return base or '#', '', '', f'/ui/{section}/{page}/{obj_id}/edit/' if obj_id else ''
    api_url = f'{base}{obj_id}/' if base and obj_id else '#'
    readonly = (section, page) in {
        ('ipam', 'histories'), ('dns', 'change-logs'), ('dhcp', 'leases'), ('dhcp', 'lease-history'),
        ('tasks', 'list'), ('tasks', 'failed'), ('audit', 'operations'),
        ('audit', 'login'), ('system', 'permissions'),
    }
    delete_url = '' if readonly or not base else api_url
    deploy_url = ''
    if (section, page) == ('dns', 'zones'):
        deploy_url = f'{api_url}push-to-pdns/'
    elif (section, page) == ('dns', 'records'):
        deploy_url = f'{api_url}push-to-pdns/'
    elif section == 'dhcp' and page in {'subnets', 'pools', 'reservations', 'options'}:
        deploy_url = '/api/dhcp/config-set/'
    edit_url = f'/ui/{section}/{page}/{obj_id}/edit/' if (section, page) in FORM_FIELDS and obj_id else ''
    return api_url, delete_url, deploy_url, edit_url


@login_required
def dashboard(request):
    total_ips = IPAddress.objects.count()
    available_ips = IPAddress.objects.filter(status='available').count()
    allocated_ips = IPAddress.objects.filter(status__in=['used', 'dhcp_dynamic', 'dhcp_reserved']).count()
    reserved_ips = IPAddress.objects.filter(status='reserved').count()
    disabled_ips = IPAddress.objects.filter(status='disabled').count()
    recent_changes = DNSChangeLog.objects.filter(created_at__gte=timezone.now() - timedelta(hours=24)).count()

    subnet_labels, subnet_usage = [], []
    for subnet in Subnet.objects.all()[:10]:
        total = subnet.ip_addresses.count()
        used = subnet.ip_addresses.exclude(status='available').count()
        subnet_labels.append(subnet.cidr)
        subnet_usage.append(round((used / total) * 100, 1) if total else 0)

    status_rows = IPAddress.objects.values('status').annotate(total=Count('id')).order_by('status')
    status_labels = [status_label(row['status']) for row in status_rows] or ['暂无数据']
    status_values = [row['total'] for row in status_rows] or [1]

    lease_labels, lease_values = [], []
    today = timezone.localdate()
    for index in range(6, -1, -1):
        day = today - timedelta(days=index)
        lease_labels.append(day.strftime('%m-%d'))
        lease_values.append(DHCPLease.objects.filter(created_at__date__lte=day).count())

    services = list(ServiceHealthCheck.objects.all()[:8])
    if not services:
        services = [
            {'service_name': 'ddi-web', 'status': 'unknown', 'status_label': '未知', 'ip_address': None, 'port': 8000, 'checked_at': None, 'response_time_ms': None},
            {'service_name': 'ddi-mysql', 'status': 'unknown', 'status_label': '未知', 'ip_address': None, 'port': 3306, 'checked_at': None, 'response_time_ms': None},
            {'service_name': 'ddi-pdns', 'status': 'unknown', 'status_label': '未知', 'ip_address': None, 'port': 8081, 'checked_at': None, 'response_time_ms': None},
            {'service_name': 'ddi-kea', 'status': 'unknown', 'status_label': '未知', 'ip_address': None, 'port': 8000, 'checked_at': None, 'response_time_ms': None},
        ]
    else:
        for service in services:
            service.status_label = status_label(service.status)

    recent_tasks = list(SystemTask.objects.all()[:10])
    for task in recent_tasks:
        task.status_label = status_label(task.status)

    context = {
        'section_title': '首页',
        'page_title': '首页仪表盘',
        'page_description': '集中查看 IPAM、DNS、DHCP、任务和审计的运行态势。',
        'active_menu': 'dashboard',
        'stat_cards': [
            {'label': 'IP 地址总数', 'value': total_ips, 'trend': '全局纳管地址', 'icon': 'IP', 'color': ''},
            {'label': '已使用 IP 数', 'value': allocated_ips, 'trend': '含静态与 DHCP 分配', 'icon': '↗', 'color': 'stat-green'},
            {'label': '可用 IP 数', 'value': available_ips, 'trend': '可继续分配', 'icon': '✓', 'color': 'stat-cyan'},
            {'label': 'DHCP 地址池数量', 'value': DHCPPool.objects.count(), 'trend': 'Kea 地址池', 'icon': '⇄', 'color': 'stat-orange'},
            {'label': 'DNS Zone 数量', 'value': DNSZone.objects.count(), 'trend': 'PowerDNS Zone', 'icon': 'Z', 'color': 'stat-purple'},
            {'label': 'DNS 记录数量', 'value': DNSRecord.objects.count(), 'trend': '全部解析记录', 'icon': 'R', 'color': ''},
            {'label': '当前 DHCP 租约数量', 'value': DHCPLease.objects.count(), 'trend': '当前租约快照', 'icon': 'L', 'color': 'stat-green'},
            {'label': '24 小时配置变更', 'value': recent_changes, 'trend': '最近 DNS 配置变更', 'icon': '!', 'color': 'stat-red'},
        ],
        'services': services,
        'recent_tasks': recent_tasks,
        'stats': {
            'ip_total': total_ips,
            'ip_allocated': allocated_ips,
            'ip_available': available_ips,
            'ip_reserved': reserved_ips,
            'ip_conflict': 0,
            'subnet_count': IPAddress.objects.values('subnet').distinct().count(),
            'dns_record_count': DNSRecord.objects.count(),
            'dhcp_pool_count': DHCPPool.objects.count(),
            'active_lease_count': DHCPLease.objects.count(),
            'device_count': 0,
            'disabled_ips': disabled_ips,
        },
        'chart_data': {
            'subnet_labels': subnet_labels or ['暂无网段'],
            'subnet_usage': subnet_usage or [0],
            'status_labels': status_labels,
            'status_values': status_values,
            'lease_labels': lease_labels,
            'lease_values': lease_values,
        },
        'recent_audit_logs': AuditLog.objects.all()[:10],
        'now_label': request.user.last_login,
    }
    return render(request, 'dashboard/index.html', context)


PAGE_META = {
    ('ipam', 'address-spaces'): ('IPAM 管理', '地址空间', '管理多租户、地域或业务域地址空间。', AddressSpace),
    ('ipam', 'subnets'): ('IPAM 管理', '网段管理', '查看 CIDR、VLAN、位置和地址利用率。', Subnet),
    ('ipam', 'ip-addresses'): ('IPAM 管理', 'IP 地址管理', '管理 IP 分配、释放、预留、禁用和关联关系。', IPAddress),
    ('ipam', 'utilization'): ('IPAM 管理', '地址利用率', '按网段跟踪容量水位和高风险地址池。', Subnet),
    ('ipam', 'histories'): ('IPAM 管理', 'IP 使用历史', '追踪 IP 地址生命周期变更记录。', IPAddressHistory),
    ('dns', 'zones'): ('DNS 管理', 'Zone 管理', '管理 PowerDNS Zone、DNSSEC 和同步状态。', DNSZone),
    ('dns', 'service'): ('DNS 管理', 'DNS 服务配置', '配置 PowerDNS API 地址、端口、API Key、Server ID 和健康检查。', DNSProviderConfig),
    ('dns', 'records'): ('DNS 管理', '记录管理', '查询和维护 A、AAAA、CNAME、MX、TXT、PTR 等记录。', DNSRecord),
    ('dns', 'change-logs'): ('DNS 管理', 'DNS 变更日志', '审计 DNS 配置下发和同步结果。', DNSChangeLog),
    ('dhcp', 'subnets'): ('DHCP 管理', 'DHCP 子网', '维护 Kea DHCP 子网、租约时间和下发状态。', DHCPSubnet),
    ('dhcp', 'service'): ('DHCP 管理', 'Kea 服务配置', '配置 Kea Control Agent API、认证信息、服务类型和健康检查。', DHCPProviderConfig),
    ('dhcp', 'pools'): ('DHCP 管理', '地址池管理', '管理 DHCP 地址池范围和容量利用率。', DHCPPool),
    ('dhcp', 'reservations'): ('DHCP 管理', '保留地址', '维护固定地址、MAC、Hostname 和 Client ID。', DHCPReservation),
    ('dhcp', 'options'): ('DHCP 管理', 'DHCP Option', '配置作用域级 DHCP Option。', DHCPOption),
    ('dhcp', 'leases'): ('DHCP 管理', '当前租约', '查看当前租约并支持转固定保留地址。', DHCPLease),
    ('dhcp', 'lease-history'): ('DHCP 管理', '租约历史', '查看已过期、已释放和历史 DHCP 租约。', DHCPLease),
    ('tasks', 'list'): ('任务中心', '任务列表', '查看配置下发、同步和后台任务状态。', SystemTask),
    ('tasks', 'logs'): ('任务中心', '任务日志', '查看任务执行过程日志。', TaskLog),
    ('tasks', 'failed'): ('任务中心', '失败任务', '聚焦需要处理的失败任务。', SystemTask),
    ('audit', 'operations'): ('审计日志', '操作审计', '记录用户操作、对象、结果和来源。', AuditLog),
    ('audit', 'login'): ('审计日志', '登录日志', '查看登录成功与失败记录。', LoginLog),
    ('audit', 'changes'): ('审计日志', '配置变更日志', '查看 DNS 配置变更和下发结果。', DNSChangeLog),
    ('system', 'users'): ('系统管理', '用户管理', '管理平台用户、状态和角色关系。', get_user_model()),
    ('system', 'roles'): ('系统管理', '角色管理', '管理角色与权限集合。', Role),
    ('system', 'permissions'): ('系统管理', '权限管理', '查看系统权限编码和模块动作。', Permission),
    ('system', 'configs'): ('系统管理', '系统配置', '维护平台级配置项。', SystemConfig),
    ('system', 'health'): ('系统管理', '健康检查', '查看组件健康检查结果。', ServiceHealthCheck),
}


def build_rows(section, page, objects):
    rows = []
    for obj in objects:
        deployable = section in ('dns', 'dhcp') and page in ('zones', 'records', 'subnets')
        if isinstance(obj, AddressSpace):
            cells = [cell(obj.name), cell(obj.code), cell(obj.description, True), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, Subnet):
            total = obj.ip_addresses.count()
            used = obj.ip_addresses.exclude(status='available').count()
            usage = round((used / total) * 100) if total else 0
            cells = [cell(obj.cidr), cell(obj.gateway), cell(obj.vlan_id), cell(obj.vlan_name), cell(obj.usage_type), cell(obj.location), cell(total), cell(used), cell(max(total - used, 0)), cell(progress(usage)), cell(badge(obj.status))]
        elif isinstance(obj, IPAddress):
            cells = [cell(obj.ip_address), cell(obj.hostname), cell(obj.mac_address), cell(obj.subnet.cidr if obj.subnet_id else '-'), cell(badge(obj.status)), cell(obj.dns_record_id or '-'), cell(obj.dhcp_reservation_id or '-'), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, IPAddressHistory):
            cells = [cell(obj.ip_address.ip_address if obj.ip_address_id else '-'), cell(obj.action), cell(obj.old_status), cell(obj.new_status), cell(obj.operator.username if obj.operator_id else '-'), cell(obj.created_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DNSProviderConfig):
            health = component_health('ddi-web -> ddi-pdns API')
            cells = [
                cell(component_association_badge(obj.api_url, 'ddi-pdns')),
                cell(badge('enabled' if dns_config_complete(obj) else 'warning', '配置完整' if dns_config_complete(obj) else '配置不完整')),
                cell(obj.api_url),
                cell(obj.api_port),
                cell(obj.server_id),
                cell('启用' if obj.use_ssl else '关闭'),
                cell('启用' if obj.health_check_enabled else '关闭'),
                *component_health_cells(health),
                cell(obj.updated_at.strftime('%Y-%m-%d %H:%M')),
            ]
        elif isinstance(obj, DNSZone):
            cells = [cell(obj.name), cell(badge(obj.kind, obj.kind)), cell('启用' if obj.dnssec else '关闭'), cell(obj.records.count()), cell(obj.soa_edit_api or '-'), cell(badge(obj.status)), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DNSRecord):
            cells = [cell(obj.zone.name if obj.zone_id else '-'), cell(obj.name, True), cell(badge(obj.record_type, obj.record_type)), cell(obj.content, True), cell(obj.ttl), cell(obj.priority or '-'), cell(badge('disabled' if obj.disabled else 'enabled')), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DNSChangeLog):
            cells = [cell(obj.zone.name if obj.zone_id else '-'), cell(obj.action), cell(obj.record_id or '-'), cell(badge(obj.result, obj.result)), cell(obj.operator.username if obj.operator_id else '-'), cell(obj.error_message, True), cell(obj.created_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DHCPProviderConfig):
            health = component_health('ddi-web -> ddi-kea API')
            cells = [
                cell(component_association_badge(obj.api_url, 'ddi-kea')),
                cell(badge('enabled' if dhcp_config_complete(obj) else 'warning', '配置完整' if dhcp_config_complete(obj) else '配置不完整')),
                cell(obj.api_url),
                cell(obj.api_port),
                cell(obj.service_type),
                cell('启用' if obj.auth_enabled else '关闭'),
                cell(obj.username or '-'),
                cell('启用' if obj.health_check_enabled else '关闭'),
                *component_health_cells(health),
                cell(obj.updated_at.strftime('%Y-%m-%d %H:%M')),
            ]
        elif isinstance(obj, DHCPSubnet):
            cells = [cell(obj.subnet), cell(obj.subnet_id), cell(obj.relay_ip or '-'), cell(obj.gateway), cell(obj.dns_servers, True), cell(obj.domain_name), cell(obj.pools.count()), cell(obj.lease_time), cell(badge(obj.status)), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DHCPPool):
            total = pool_capacity(obj)
            used = pool_used_count(obj)
            usage = round((used / total) * 100) if total else 0
            cells = [cell(obj.dhcp_subnet.subnet if obj.dhcp_subnet_id else '-'), cell(obj.pool_start), cell(obj.pool_end), cell(total), cell(used), cell(progress(usage)), cell(badge(obj.status))]
        elif isinstance(obj, DHCPReservation):
            cells = [cell(obj.dhcp_subnet.subnet if obj.dhcp_subnet_id else '-'), cell(obj.ip_address), cell(obj.mac_address), cell(obj.hostname), cell(obj.client_id, True), cell(badge(obj.status)), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DHCPOption):
            cells = [cell(obj.scope_type), cell(obj.scope_id), cell(obj.option_code), cell(obj.option_name), cell(obj.option_value, True), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, DHCPLease):
            cells = [cell(obj.ip_address), cell(obj.mac_address), cell(obj.hostname), cell(obj.subnet_id), cell(badge(obj.state or 'active', obj.state or '活跃')), cell(obj.cltt.strftime('%Y-%m-%d %H:%M') if obj.cltt else '-'), cell(obj.expire_time.strftime('%Y-%m-%d %H:%M') if obj.expire_time else '-')]
        elif isinstance(obj, SystemTask):
            cells = [cell(obj.task_type), cell(obj.target_service), cell(badge(obj.status)), cell(obj.started_at.strftime('%Y-%m-%d %H:%M') if obj.started_at else '-'), cell(obj.finished_at.strftime('%Y-%m-%d %H:%M') if obj.finished_at else '-'), cell(obj.error_message, True)]
        elif isinstance(obj, TaskLog):
            cells = [cell(obj.task_id), cell(obj.level), cell(obj.message, True), cell(obj.created_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, AuditLog):
            cells = [cell(obj.username), cell(obj.module), cell(obj.action), cell(obj.object_name or obj.object_type, True), cell(badge(obj.result, obj.result)), cell(obj.request_ip), cell(obj.created_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, LoginLog):
            cells = [cell(obj.username), cell(obj.request_ip), cell(badge(obj.result, obj.result)), cell(obj.user_agent, True), cell(obj.error_message, True), cell(obj.created_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, Role):
            cells = [cell(obj.name), cell(obj.code), cell(obj.permissions.count()), cell(obj.description, True), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, Permission):
            cells = [cell(obj.module), cell(obj.action), cell(obj.code), cell(obj.description, True)]
        elif obj.__class__.__name__ == 'User':
            cells = [cell(obj.username), cell(getattr(obj, 'real_name', '')), cell(obj.email), cell(getattr(obj, 'mobile', '')), cell(badge('enabled' if obj.is_active else 'disabled')), cell(obj.last_login.strftime('%Y-%m-%d %H:%M') if obj.last_login else '-')]
        elif isinstance(obj, SystemConfig):
            cells = [cell(obj.key), cell(obj.value, True), cell(obj.description, True), cell(obj.updated_at.strftime('%Y-%m-%d %H:%M'))]
        elif isinstance(obj, ServiceHealthCheck):
            cells = [cell(obj.service_name), cell(badge(obj.status)), cell(obj.ip_address), cell(obj.port), cell(obj.checked_at.strftime('%Y-%m-%d %H:%M')), cell(obj.response_time_ms), cell(obj.error_message, True)]
        else:
            cells = [cell(str(obj))]
        api_url, delete_url, deploy_url, edit_url = row_urls(section, page, obj.pk)
        extra_actions = []
        if isinstance(obj, DHCPLease) and page == 'leases':
            extra_actions = [
                {'label': '释放', 'class': 'btn-danger', 'url': f'/api/dhcp/leases/{obj.pk}/release/', 'success': '租约释放任务已创建'},
                {'label': '转保留', 'class': 'btn-info', 'url': f'/api/dhcp/leases/{obj.pk}/convert-to-reservation/', 'success': '已转换为保留地址'},
            ]
        rows.append({'id': obj.pk, 'cells': cells, 'api_url': api_url, 'delete_url': delete_url, 'deploy_url': deploy_url, 'edit_url': edit_url, 'deployable': deployable, 'show_delete': bool(delete_url), 'extra_actions': extra_actions})
    return rows


def columns_for(section, page):
    mapping = {
        ('ipam', 'address-spaces'): ['名称', '编码', '描述', '更新时间'],
        ('ipam', 'subnets'): ['CIDR', '网关', 'VLAN ID', 'VLAN 名称', '用途', '位置', '总数', '已使用', '可用', '利用率', '状态'],
        ('ipam', 'ip-addresses'): ['IP 地址', '主机名', 'MAC 地址', '所属网段', '状态', '关联 DNS', '关联 DHCP', '更新时间'],
        ('ipam', 'histories'): ['IP 地址', '动作', '原状态', '新状态', '操作人', '时间'],
        ('dns', 'zones'): ['Zone 名称', '类型', 'DNSSEC', '记录数量', 'SOA 信息', '同步状态', '最近更新时间'],
        ('dns', 'service'): ['关联容器', '配置状态', 'API 地址', 'API 端口', 'Server ID', 'SSL', '健康检查', '连通状态', '最近检测', '错误信息', '更新时间'],
        ('dns', 'records'): ['Zone', '记录名称', '类型', '记录内容', 'TTL', 'MX 优先级', '状态', '更新时间'],
        ('dns', 'change-logs'): ['Zone', '动作', '记录', '结果', '操作人', '错误信息', '时间'],
        ('dhcp', 'subnets'): ['子网', '子网 ID', 'Relay 地址', '网关', 'DNS Server', 'Domain Name', '地址池数量', '租约时间', '状态', '最近下发时间'],
        ('dhcp', 'service'): ['关联容器', '配置状态', 'API 地址', 'API 端口', '服务类型', '认证', '用户名', '健康检查', '连通状态', '最近检测', '错误信息', '更新时间'],
        ('dhcp', 'pools'): ['所属子网', '起始 IP', '结束 IP', '地址数量', '已使用数量', '利用率', '状态'],
        ('dhcp', 'reservations'): ['所属子网', 'IP 地址', 'MAC 地址', 'Hostname', 'Client ID', '状态', '更新时间'],
        ('dhcp', 'options'): ['作用域类型', '作用域 ID', 'Option Code', 'Option Name', 'Option Value', '更新时间'],
        ('dhcp', 'leases'): ['IP 地址', 'MAC 地址', 'Hostname', '所属子网', '租约状态', '开始时间', '过期时间'],
        ('dhcp', 'lease-history'): ['IP 地址', 'MAC 地址', 'Hostname', '所属子网', '租约状态', '开始时间', '过期时间'],
        ('tasks', 'list'): ['任务名称', '目标服务', '状态', '开始时间', '完成时间', '错误信息'],
        ('tasks', 'logs'): ['任务 ID', '级别', '日志内容', '时间'],
        ('tasks', 'failed'): ['任务名称', '目标服务', '状态', '开始时间', '完成时间', '错误信息'],
        ('audit', 'operations'): ['操作人', '模块', '动作', '操作对象', '结果', '来源 IP', '操作时间'],
        ('audit', 'login'): ['用户名', '来源 IP', '结果', 'User Agent', '错误信息', '登录时间'],
        ('audit', 'changes'): ['Zone', '动作', '记录', '结果', '操作人', '错误信息', '时间'],
        ('system', 'users'): ['用户名', '真实姓名', '邮箱', '手机号', '状态', '最近登录'],
        ('system', 'roles'): ['角色名称', '角色编码', '权限数量', '描述', '更新时间'],
        ('system', 'permissions'): ['模块', '动作', '权限编码', '描述'],
        ('system', 'configs'): ['配置键', '配置值', '描述', '更新时间'],
        ('system', 'health'): ['服务名称', '运行状态', 'IP 地址', '端口', '最近检测时间', '响应耗时', '错误详情'],
    }
    return mapping.get((section, page), ['名称', '说明', '状态', '更新时间'])


@login_required
def dns_service_page(request):
    return web_list(request, 'dns', 'service')


@login_required
def web_list(request, section, page):
    if section == 'linkage':
        raise Http404('联动管理功能已移除')
    if (section, page) == ('dns', 'service'):
        cfg = DNSService.reset_default_config()
        health = HealthService.check_pdns_api()
        recursion = dns_recursion_config()
        if request.method == 'POST':
            recursion = {
                'enabled': request.POST.get('enabled') == 'on',
                'forward_zones': normalize_forward_zones(request.POST.get('forward_zones')),
                'upstream_dns_1': normalize_upstream_dns(request.POST.get('upstream_dns_1')),
                'upstream_dns_2': normalize_upstream_dns(request.POST.get('upstream_dns_2')),
            }
            if recursion['enabled'] and not (recursion['upstream_dns_1'] or recursion['upstream_dns_2']):
                recursion['upstream_dns_1'] = DNS_RECURSION_DEFAULT['upstream_dns_1']
            SystemConfig.objects.update_or_create(
                key=DNS_RECURSION_KEY,
                defaults={'value': recursion, 'description': 'PowerDNS 前置递归转发配置'},
            )
            save_dns_recursion_runtime(recursion)
            messages.success(request, 'DNS 递归查询配置已保存，ddi-pdns 将自动重载转发配置。')
            return redirect('web-list', section=section, page=page)
        save_dns_recursion_runtime(recursion)
        return render(request, 'dns/service.html', {
            'section_title': 'DNS 管理',
            'page_title': 'DNS 服务配置',
            'page_description': '配置 PowerDNS API、权威区转发和公网递归查询。',
            'active_section': 'dns',
            'active_menu': 'service',
            'config': cfg,
            'recursion': recursion,
            'health': health,
            'health_label': status_label(health.get('status')),
            'runtime_path': 'docker/pdns/runtime/recursion.env',
        })
    if False and (section, page) == ('dns', 'records'):
        mode = request.GET.get('mode', 'all')
        if request.method == 'POST':
            mode = request.POST.get('mode') or mode
            try:
                action = request.POST.get('action') or 'save'
                record_id = request.POST.get('record_id')
                if action in {'push', 'delete'}:
                    record = get_object_or_404(DNSRecord.objects.select_related('zone'), pk=record_id)
                    if action == 'push':
                        result = DNSService.push_record(record, user=request.user, request=request)
                        level = messages.success if result.get('success') else messages.error
                        level(request, dns_record_result_message(result, 'DNS 记录已重新下发。'))
                    else:
                        result = delete_dns_record(record)
                        if result.get('success'):
                            record.delete()
                            messages.success(request, 'DNS 记录已从 PowerDNS 和本地删除。')
                        else:
                            messages.error(request, result.get('message') or 'DNS 记录删除失败。')
                    return redirect(f'/ui/dns/records/?mode={mode}')

                record_type = request.POST.get('record_type') or 'A'
                ttl = int(request.POST.get('ttl') or 3600)
                record = DNSRecord.objects.select_related('zone').filter(pk=record_id).first() if record_id else None
                if record_type == 'PTR':
                    ip_value = request.POST.get('ip_address')
                    content = request.POST.get('target') or request.POST.get('content') or ''
                    if ip_value:
                        reverse_zone_name, ptr_name = reverse_zone_for_ipv4(ip_value)
                        zone = ensure_dns_zone(reverse_zone_name, user=request.user, request=request)
                    elif record:
                        zone = record.zone
                        ptr_name = record.name
                    else:
                        raise ValueError('PTR 记录需要填写 IP 地址')
                    if record:
                        record.zone = zone
                        record.name = ptr_name
                        record.record_type = 'PTR'
                        record.content = content
                        record.ttl = ttl
                        record.priority = None
                        record.comment = '记录管理页面更新 PTR'
                        record.disabled = False
                        record.save()
                        result = DNSService.push_record(record, user=request.user, request=request)
                    else:
                        record, result = upsert_dns_record(
                            zone, ptr_name, 'PTR', content, ttl=ttl,
                            comment='记录管理页面创建 PTR', user=request.user, request=request,
                        )
                else:
                    zone = DNSZone.objects.filter(pk=request.POST.get('zone_id')).first()
                    zone_name = request.POST.get('zone_name') or (zone.name if zone else '')
                    zone = ensure_dns_zone(zone_name, user=request.user, request=request)
                    name = request.POST.get('name') or '@'
                    content = request.POST.get('content') or ''
                    priority = int(request.POST.get('priority') or 10) if record_type == 'MX' else None
                    if record:
                        record.zone = zone
                        record.name = name
                        record.record_type = record_type
                        record.content = content
                        record.ttl = ttl
                        record.priority = priority
                        record.comment = '记录管理页面更新'
                        record.disabled = False
                        record.save()
                        result = DNSService.push_record(record, user=request.user, request=request)
                    else:
                        record, result = upsert_dns_record(
                            zone, name, record_type, content, ttl=ttl, priority=priority,
                            comment='记录管理页面创建', user=request.user, request=request,
                        )
                    if result.get('success') and request.POST.get('create_ptr') == 'on' and record_type == 'A':
                        reverse_zone_name, ptr_name = reverse_zone_for_ipv4(content)
                        reverse_zone = ensure_dns_zone(reverse_zone_name, user=request.user, request=request)
                        ptr_target = DNSService.canonical_record_name(name, zone.name)
                        _, ptr_result = upsert_dns_record(
                            reverse_zone, ptr_name, 'PTR', ptr_target, ttl=ttl,
                            comment=f'由 {record.name} 自动创建', user=request.user, request=request,
                        )
                        if not ptr_result.get('success'):
                            messages.warning(request, f'记录已下发，PTR 创建失败：{ptr_result.get("message")}')
                        else:
                            messages.success(request, '记录和 PTR 已下发。')
                            return redirect(f'/ui/dns/records/?mode={mode}')
                level = messages.success if result.get('success') else messages.error
                level(request, dns_record_result_message(result, 'DNS 记录已下发。'))
            except Exception as exc:
                messages.error(request, f'DNS 记录保存失败：{exc}')
            return redirect(f'/ui/dns/records/?mode={mode}')

        records = DNSRecord.objects.select_related('zone').order_by('-updated_at')
        record_type = request.GET.get('record_type', '').strip()
        zone_id = request.GET.get('zone_id', '').strip()
        q = request.GET.get('q', '').strip()
        if mode == 'forward':
            records = records.filter(record_type__in=['A', 'AAAA', 'CNAME', 'MX'])
        elif mode == 'reverse':
            records = records.filter(record_type='PTR')
        elif record_type:
            records = records.filter(record_type=record_type)
        if zone_id:
            records = records.filter(zone_id=zone_id)
        if q:
            records = records.filter(Q(name__icontains=q) | Q(content__icontains=q) | Q(zone__name__icontains=q))
        total = records.count()
        edit_record = DNSRecord.objects.select_related('zone').filter(pk=request.GET.get('edit')).first()
        selected_record_type = edit_record.record_type if edit_record else ('PTR' if mode == 'reverse' else 'A')
        selected_zone_id = edit_record.zone_id if edit_record else ''
        return render(request, 'dns/records.html', {
            'section_title': 'DNS 管理',
            'page_title': 'DNS 记录管理',
            'page_description': '统一维护正向解析、反向解析和通用 DNS 记录，避免多入口配置冲突。',
            'active_section': 'dns',
            'active_menu': 'records',
            'mode': mode,
            'q': q,
            'record_type': record_type,
            'zone_id': zone_id,
            'record_types': ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'PTR', 'SRV', 'CAA'],
            'zones': DNSZone.objects.filter(status='enabled').order_by('name'),
            'records': records[:50],
            'total_count': total,
            'edit_record': edit_record,
            'selected_record_type': selected_record_type,
            'selected_zone_id': selected_zone_id,
            'summary': {
                'total': DNSRecord.objects.count(),
                'forward': DNSRecord.objects.filter(record_type__in=['A', 'AAAA', 'CNAME', 'MX']).count(),
                'reverse': DNSRecord.objects.filter(record_type='PTR').count(),
                'unsynced': DNSRecord.objects.filter(synced_at__isnull=True).count(),
            },
            'tasks': latest_dns_tasks(),
        })
    if (section, page) == ('dns', 'forward'):
        return redirect('/ui/dns/records/?mode=forward')
    if (section, page) == ('dns', 'reverse'):
        return redirect('/ui/dns/records/?mode=reverse')
    if False and (section, page) == ('dns', 'forward'):
        if request.method == 'POST':
            try:
                zone = DNSZone.objects.filter(pk=request.POST.get('zone_id')).first()
                zone_name = request.POST.get('zone_name') or (zone.name if zone else '')
                zone = ensure_dns_zone(zone_name, user=request.user, request=request)
                record_type = request.POST.get('record_type') or 'A'
                name = request.POST.get('name') or '@'
                content = request.POST.get('content') or ''
                ttl = int(request.POST.get('ttl') or 3600)
                priority = int(request.POST.get('priority') or 10) if record_type == 'MX' else None
                record, result = upsert_dns_record(
                    zone, name, record_type, content, ttl=ttl, priority=priority,
                    comment='正向解析页面创建', user=request.user, request=request,
                )
                if result.get('success') and request.POST.get('create_ptr') == 'on' and record_type == 'A':
                    reverse_zone_name, ptr_name = reverse_zone_for_ipv4(content)
                    reverse_zone = ensure_dns_zone(reverse_zone_name, user=request.user, request=request)
                    ptr_target = DNSService.canonical_record_name(name, zone.name)
                    _, ptr_result = upsert_dns_record(
                        reverse_zone, ptr_name, 'PTR', ptr_target, ttl=ttl,
                        comment=f'由 {record.name} 自动创建', user=request.user, request=request,
                    )
                    if not ptr_result.get('success'):
                        messages.warning(request, f'正向记录已下发，PTR 创建失败：{ptr_result.get("message")}')
                    else:
                        messages.success(request, '正向记录和 PTR 记录已下发。')
                else:
                    level = messages.success if result.get('success') else messages.error
                    level(request, dns_record_result_message(result, '正向记录已下发。'))
            except Exception as exc:
                messages.error(request, f'正向解析保存失败：{exc}')
            return redirect('web-list', section=section, page=page)
        records = DNSRecord.objects.select_related('zone').filter(record_type__in=['A', 'AAAA', 'CNAME', 'MX']).order_by('-updated_at')[:50]
        return render(request, 'dns/forward.html', {
            'section_title': 'DNS 管理',
            'page_title': '正向解析',
            'page_description': '维护主机名到 IP 或别名的解析记录，并支持 A 记录自动创建 PTR。',
            'active_section': 'dns',
            'active_menu': 'forward',
            'zones': DNSZone.objects.filter(status='enabled').order_by('name'),
            'records': records,
            'tasks': latest_dns_tasks(),
        })
    if False and (section, page) == ('dns', 'reverse'):
        if request.method == 'POST':
            try:
                ip_value = request.POST.get('ip_address') or ''
                target = request.POST.get('target') or ''
                ttl = int(request.POST.get('ttl') or 3600)
                reverse_zone_name, ptr_name = reverse_zone_for_ipv4(ip_value)
                zone = ensure_dns_zone(reverse_zone_name, user=request.user, request=request)
                record, result = upsert_dns_record(
                    zone, ptr_name, 'PTR', target, ttl=ttl,
                    comment=f'反向解析页面创建：{ip_value}', user=request.user, request=request,
                )
                level = messages.success if result.get('success') else messages.error
                level(request, dns_record_result_message(result, 'PTR 记录已下发。'))
            except Exception as exc:
                messages.error(request, f'反向解析保存失败：{exc}')
            return redirect('web-list', section=section, page=page)
        records = DNSRecord.objects.select_related('zone').filter(record_type='PTR').order_by('-updated_at')[:50]
        return render(request, 'dns/reverse.html', {
            'section_title': 'DNS 管理',
            'page_title': '反向解析',
            'page_description': '维护 IPv4 PTR 记录，自动生成 in-addr.arpa 反向 Zone。',
            'active_section': 'dns',
            'active_menu': 'reverse',
            'records': records,
            'tasks': latest_dns_tasks(),
        })
    if (section, page) == ('dns', 'sync'):
        cfg = DNSService.ensure_config()
        health = HealthService.check_pdns_api()
        tasks = SystemTask.objects.filter(task_type__in=['dns_zone_sync', 'dns_record_sync']).order_by('-created_at')[:10]
        logs = DNSChangeLog.objects.filter(action__in=['sync_zones', 'sync_all_records', 'push_zone', 'push_record_replace']).order_by('-created_at')[:10]
        zones = DNSZone.objects.prefetch_related('records').order_by('name')[:20]
        return render(request, 'dns/sync.html', {
            'section_title': 'DNS 管理',
            'page_title': 'DNS 数据同步',
            'active_section': 'dns',
            'active_menu': 'sync',
            'zones': zones,
            'tasks': tasks,
            'logs': logs,
            'summary': {
                'zone_count': DNSZone.objects.count(),
                'record_count': DNSRecord.objects.count(),
                'sync_task_count': SystemTask.objects.filter(task_type__in=['dns_zone_sync', 'dns_record_sync']).count(),
                'health_label': status_label(health.get('status')),
                'api_url': cfg.api_url,
            },
        })
    if (section, page) == ('dhcp', 'deploy'):
        subnets = DHCPSubnet.objects.prefetch_related('pools', 'reservations').filter(status='enabled').order_by('subnet_id')
        subnet_rows = DHCPService.subnet_deploy_rows(subnets)
        tasks = SystemTask.objects.filter(task_type__in=['dhcp_config_test', 'dhcp_config_apply', 'dhcp_config_reload']).order_by('-created_at')[:10]
        valid_reservations = DHCPService.valid_reservations_queryset().filter(dhcp_subnet__status='enabled')
        invalid_reservations = DHCPReservation.objects.filter(status='enabled', dhcp_subnet__status='enabled', mac_address='', client_id='')
        return render(request, 'dhcp/deploy.html', {
            'section_title': 'DHCP 管理',
            'page_title': 'DHCP 配置下发',
            'active_section': 'dhcp',
            'active_menu': 'deploy',
            'subnet_rows': subnet_rows,
            'tasks': tasks,
            'summary': {
                'enabled_subnets': subnets.count(),
                'deployed_subnets': sum(1 for row in subnet_rows if row['deploy_status'] == 'success'),
                'pending_subnets': sum(1 for row in subnet_rows if row['deploy_status'] != 'success'),
                'enabled_pools': DHCPPool.objects.filter(status='enabled', dhcp_subnet__status='enabled').count(),
                'enabled_reservations': valid_reservations.count(),
                'invalid_reservations': invalid_reservations.count(),
                'options': DHCPOption.objects.count(),
            },
        })
    meta = PAGE_META.get((section, page))
    if meta:
        section_title, page_title, description, model = meta
        ensure_component_config(section, page)
        if (section, page) in {('dhcp', 'leases'), ('dhcp', 'lease-history')}:
            DHCPService.sync_leases(request)
        qs = model.objects.all()
        if (section, page) == ('dhcp', 'leases'):
            qs = qs.filter(state='active')
        elif (section, page) == ('dhcp', 'lease-history'):
            qs = qs.exclude(state='active')
        if (section, page) == ('tasks', 'failed'):
            qs = qs.filter(status='failed')
        q = request.GET.get('q', '').strip()
        if q:
            search = Q()
            for field in ('name', 'code', 'cidr', 'ip_address', 'hostname', 'mac_address', 'username', 'module', 'action', 'object_name', 'task_type', 'target_service', 'subnet', 'content', 'description'):
                try:
                    model._meta.get_field(field)
                except Exception:
                    continue
                search |= Q(**{f'{field}__icontains': q})
            if search:
                qs = qs.filter(search)
        status = request.GET.get('status')
        if status:
            for field in ('status', 'result', 'state', 'is_active'):
                try:
                    model._meta.get_field(field)
                except Exception:
                    continue
                qs = qs.filter(**{field: status})
                break
        total = qs.count()
        objects = qs[:30]
        rows = build_rows(section, page, objects)
        columns = columns_for(section, page)
    else:
        section_title = {'dns': 'DNS 管理', 'dhcp': 'DHCP 管理', 'system': '系统管理', 'tasks': '任务中心', 'audit': '审计日志', 'ipam': 'IPAM 管理'}.get(section, section)
        page_title = page.replace('-', ' ').title()
        description = '该功能入口已纳入统一导航，后续可接入对应业务数据。'
        total, rows, columns = 0, [], ['名称', '说明', '状态', '更新时间']
    return render(request, 'generic_list.html', {
        'section_title': section_title,
        'page_title': page_title,
        'page_description': description,
        'primary_action': '' if (section, page) in {('dns', 'service'), ('dhcp', 'service')} else '新增',
        'active_section': section,
        'active_menu': page,
        'columns': columns,
        'rows': rows,
        'total_count': total,
        'export_url': EXPORT_URLS.get((section, page), ''),
        'import_url': IMPORT_URLS.get((section, page), ''),
        'bulk_delete_url': '/api/dns/records/bulk-delete/' if (section, page) == ('dns', 'records') else '',
        'create_url': f'/ui/{section}/{page}/new/' if (section, page) in FORM_FIELDS else '',
        'show_import_export': (section, page) not in {('dns', 'service'), ('dhcp', 'service')},
        'show_bulk_actions': (section, page) not in {('dns', 'service'), ('dhcp', 'service')},
    })


@login_required
def web_create(request, section, page):
    if section == 'linkage':
        raise Http404('联动管理功能已移除')
    if (section, page) == ('dns', 'records'):
        if request.method == 'POST':
            try:
                save_dns_record_from_form(request)
                messages.success(request, 'DNS 记录已保存，列表中可继续执行下发。')
                return redirect('web-list', section=section, page=page)
            except Exception as exc:
                messages.error(request, f'DNS 记录保存失败：{exc}')
        return render(request, 'dns/record_form.html', dns_record_form_context(request))
    meta, fields = form_model_meta(section, page)
    if not meta:
        return redirect('web-list', section=section, page=page)
    cfg = ensure_component_config(section, page)
    if cfg:
        return redirect('web-edit', section=section, page=page, pk=cfg.pk)
    section_title, list_title, description, model = meta
    FormClass = modelform_factory(model, fields=fields)
    form = FormClass(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        if isinstance(obj, Subnet):
            result = IPAMService.generate_ips(obj)
            messages.success(request, f'网段已保存，已生成 {result["created"]} 个 IP 地址。')
        elif isinstance(obj, DHCPReservation):
            DHCPService.mark_reservation_ipam(obj, request.user)
        return redirect('web-list', section=section, page=page)
    return render(request, 'generic_form.html', {
        'section_title': section_title,
        'page_title': f'新增{list_title}',
        'page_description': description,
        'form_title': f'新增{list_title}',
        'form': form,
        'back_url': f'/ui/{section}/{page}/',
        'active_section': section,
        'active_menu': page,
    })


@login_required
def web_edit(request, section, page, pk):
    if section == 'linkage':
        raise Http404('联动管理功能已移除')
    if (section, page) == ('dns', 'records'):
        instance = get_object_or_404(DNSRecord.objects.select_related('zone'), pk=pk)
        if request.method == 'POST':
            try:
                save_dns_record_from_form(request, instance)
                messages.success(request, 'DNS 记录已更新，列表中可继续执行下发。')
                return redirect('web-list', section=section, page=page)
            except Exception as exc:
                messages.error(request, f'DNS 记录保存失败：{exc}')
        return render(request, 'dns/record_form.html', dns_record_form_context(request, instance))
    meta, fields = form_model_meta(section, page)
    if not meta:
        return redirect('web-list', section=section, page=page)
    section_title, list_title, description, model = meta
    instance = get_object_or_404(model, pk=pk)
    FormClass = modelform_factory(model, fields=fields)
    form = FormClass(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        if isinstance(obj, Subnet):
            IPAMService.generate_ips(obj)
        elif isinstance(obj, DHCPReservation):
            DHCPService.mark_reservation_ipam(obj, request.user)
        return redirect('web-list', section=section, page=page)
    return render(request, 'generic_form.html', {
        'section_title': section_title,
        'page_title': f'编辑{list_title}',
        'page_description': description,
        'form_title': f'编辑{list_title}',
        'form': form,
        'back_url': f'/ui/{section}/{page}/',
        'active_section': section,
        'active_menu': page,
    })
@api_view(['GET'])
def health_view(request): return success_response({'status':'ok'})
@api_view(['GET'])
def dashboard_stats(request):
    total=IPAddress.objects.count(); available=IPAddress.objects.filter(status='available').count()
    return success_response({'ip_total':total,'ip_used':total-available,'ip_available':available,'dhcp_pool_count':DHCPPool.objects.count(),'dns_zone_count':DNSZone.objects.count(),'dns_record_count':DNSRecord.objects.count(),'dhcp_lease_count':DHCPLease.objects.count(),'recent_tasks':SystemTask.objects.count(),'recent_audit_logs':AuditLog.objects.count()})
@api_view(['GET'])
def services_view(request): return success_response(ServiceHealthCheckSerializer(ServiceHealthCheck.objects.all()[:20], many=True).data)
@api_view(['POST'])
def check_now_view(request): return success_response(HealthService.check_all())
class SystemConfigViewSet(viewsets.ModelViewSet): queryset=SystemConfig.objects.all(); serializer_class=SystemConfigSerializer
