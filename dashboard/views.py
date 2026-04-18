from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from ipam.models import Region, Subnet, IPAddress
from dnsmgr.models import DNSZone, DNSRecord
from dhcpmgr.models import DHCPPool, DHCPLease
from devices.models import Device
from logs.models import OperationLog


@login_required
def index(request):
    """首页仪表盘"""
    
    # ========== 基础统计 ==========
    stats = {
        # IPAM 统计
        'region_count': Region.objects.count(),
        'subnet_count': Subnet.objects.count(),
        'ip_total': IPAddress.objects.count(),
        'ip_allocated': IPAddress.objects.filter(status='allocated').count(),
        'ip_available': IPAddress.objects.filter(status='available').count(),
        'ip_reserved': IPAddress.objects.filter(status='reserved').count(),
        'ip_conflict': IPAddress.objects.filter(status='conflict').count(),
        
        # DNS 统计
        'dns_zone_count': DNSZone.objects.count(),
        'dns_record_count': DNSRecord.objects.count(),
        
        # DHCP 统计
        'dhcp_pool_count': DHCPPool.objects.filter(status='enabled').count(),
        'dhcp_active_lease': DHCPLease.objects.filter(status='active').count(),
        
        # 设备统计
        'device_count': Device.objects.count(),
    }
    
    # 计算IP使用率
    if stats['ip_total'] > 0:
        stats['ip_usage_percent'] = round((stats['ip_allocated'] / stats['ip_total']) * 100, 1)
    else:
        stats['ip_usage_percent'] = 0
    
    # ========== 子网使用情况（用于图表）==========
    subnet_stats = []
    for subnet in Subnet.objects.all()[:10]:
        total_ips = subnet.total_ips if hasattr(subnet, 'total_ips') else 0
        allocated = subnet.ip_addresses.filter(status='allocated').count()
        available = total_ips - allocated
        
        subnet_stats.append({
            'name': subnet.name,
            'cidr': subnet.cidr,
            'total': total_ips,
            'allocated': allocated,
            'available': max(0, available),
            'usage_rate': round((allocated / total_ips) * 100, 1) if total_ips > 0 else 0,
        })
    
    # ========== 各VLAN地址分布 ==========
    vlan_data = []
    vlans_with_subnets = Subnet.objects.values('vlan__vlan_id', 'vlan__name').annotate(
        ip_count=Count('ip_addresses')
    ).exclude(vlan__vlan_id=None)[:8]
    
    for item in vlans_with_subnets:
        vlan_data.append({
            'vlan_id': item['vlan__vlan_id'],
            'vlan_name': item['vlan__name'] or f'VLAN{item["vlan__vlan_id"]}',
            'count': item['ip_count'],
        })
    
    # ========== DNS记录类型分布 ==========
    dns_type_stats = DNSRecord.objects.values('record_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    dns_types = {item['record_type']: item['count'] for item in dns_type_stats}
    
    # ========== 最近操作记录 ==========
    recent_logs = OperationLog.objects.select_related('user')[:15]
    
    # ========== 告警信息 ==========
    alerts = []
    
    # 检测高使用率子网(>80%)
    for subnet in Subnet.objects.all():
        if hasattr(subnet, 'usage_percent') and subnet.usage_percent > 80:
            alerts.append({
                'level': 'danger' if subnet.usage_percent > 90 else 'warning',
                'message': f'子网 {subnet.cidr} 使用率已达 {subnet.usage_percent}%',
                'type': 'subnet_usage'
            })
    
    # 检测冲突IP
    conflict_count = stats.get('ip_conflict', 0)
    if conflict_count > 0:
        alerts.append({
            'level': 'danger',
            'message': f'存在 {conflict_count} 个冲突IP地址',
            'type': 'ip_conflict'
        })
    
    context = {
        'stats': stats,
        'subnet_stats': subnet_stats,
        'vlan_data': vlan_data,
        'dns_types': dns_types,
        'recent_logs': recent_logs,
        'alerts': alerts[:5],
    }
    
    return render(request, 'dashboard/index.html', context)
