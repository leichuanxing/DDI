import ipaddress

import pymysql
from django.db import transaction
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from urllib.parse import urlparse

from common.audit import write_audit
from ipam.models import IPAddress
from ipam.services import IPAMService

from .clients import KeaClient
from .models import DHCPLease, DHCPOption, DHCPProviderConfig, DHCPReservation, DHCPSubnet


class DHCPService:
    @staticmethod
    def default_config_values():
        api_url = getattr(settings, 'KEA_API_URL', 'http://ddi-kea:8000')
        parsed = urlparse(api_url)
        return {
            'api_url': api_url,
            'api_port': parsed.port or 8000,
            'service_type': 'dhcp4',
            'timeout': 5,
            'auth_enabled': False,
            'username': '',
            'password': '',
            'health_check_enabled': True,
        }

    @classmethod
    def ensure_config(cls):
        cfg = DHCPProviderConfig.objects.order_by('-id').first()
        if cfg:
            return cfg
        return DHCPProviderConfig.objects.create(**cls.default_config_values())

    @classmethod
    def reset_default_config(cls):
        cfg = cls.ensure_config()
        defaults = cls.default_config_values()
        for key, value in defaults.items():
            setattr(cfg, key, value)
        cfg.save()
        return cfg

    @staticmethod
    def client():
        cfg = DHCPService.ensure_config()
        auth = (cfg.username, cfg.password) if cfg.auth_enabled else None
        return KeaClient(cfg.api_url, cfg.timeout, auth)

    @classmethod
    def client_for_config(cls, cfg):
        auth = (cfg.username, cfg.password) if cfg.auth_enabled else None
        return KeaClient(cfg.api_url, cfg.timeout, auth)

    @staticmethod
    def build_dhcp4_config():
        subnets = []
        for subnet in DHCPSubnet.objects.prefetch_related('pools', 'reservations').filter(status='enabled').order_by('subnet_id'):
            pools = []
            for pool in subnet.pools.filter(status='enabled'):
                pool_item = {'pool': f'{pool.pool_start} - {pool.pool_end}'}
                pool_options = [
                    {'code': opt.option_code, 'name': opt.option_name, 'data': opt.option_value}
                    for opt in DHCPOption.objects.filter(scope_type='pool', scope_id=pool.id).order_by('option_code')
                ]
                if pool_options:
                    pool_item['option-data'] = pool_options
                pools.append(pool_item)
            reservations = []
            for r in subnet.reservations.filter(status='enabled'):
                if not DHCPService.reservation_has_identifier(r):
                    continue
                item = {'ip-address': str(r.ip_address)}
                if r.mac_address:
                    item['hw-address'] = r.mac_address
                if r.client_id:
                    item['client-id'] = r.client_id
                if r.hostname:
                    item['hostname'] = r.hostname
                reservations.append(item)
            options = []
            if subnet.gateway:
                options.append({'name': 'routers', 'data': str(subnet.gateway)})
            if subnet.dns_servers:
                options.append({'name': 'domain-name-servers', 'data': subnet.dns_servers})
            if subnet.domain_name:
                options.append({'name': 'domain-name', 'data': subnet.domain_name})
            for opt in DHCPOption.objects.filter(scope_type='subnet', scope_id=subnet.id).order_by('option_code'):
                options.append({'code': opt.option_code, 'name': opt.option_name, 'data': opt.option_value})
            subnet_item = {
                'id': subnet.subnet_id,
                'subnet': subnet.subnet,
                'pools': pools,
                'reservations': reservations,
                'option-data': options,
                'valid-lifetime': subnet.valid_lifetime,
                'renew-timer': subnet.renew_timer,
                'rebind-timer': subnet.rebind_timer,
            }
            if subnet.interface:
                subnet_item['interface'] = subnet.interface
            if subnet.relay_ip:
                subnet_item['relay'] = {'ip-addresses': [str(subnet.relay_ip)]}
            subnets.append(subnet_item)
        global_options = [
            {'code': o.option_code, 'name': o.option_name, 'data': o.option_value}
            for o in DHCPOption.objects.filter(scope_type='global').order_by('option_code')
        ]
        return {
            'Dhcp4': {
                'interfaces-config': {'interfaces': ['*']},
                'control-socket': {'socket-type': 'unix', 'socket-name': '/tmp/kea4-ctrl-socket'},
                'lease-database': {'type': 'mysql', 'host': 'ddi-mysql', 'name': 'kea', 'user': 'ddi', 'password': 'ddi_password'},
                'valid-lifetime': 3600,
                'renew-timer': 900,
                'rebind-timer': 1800,
                'subnet4': subnets,
                'option-data': global_options,
                'loggers': [{'name': 'kea-dhcp4', 'severity': 'INFO'}],
            }
        }

    @staticmethod
    def reservation_has_identifier(reservation):
        return bool((reservation.mac_address or '').strip() or (reservation.client_id or '').strip())

    @staticmethod
    def valid_reservations_queryset():
        return DHCPReservation.objects.filter(status='enabled').filter(Q(mac_address__gt='') | Q(client_id__gt=''))

    @classmethod
    def config_test(cls, service='dhcp4'):
        return cls.client().config_test(service, cls.build_dhcp4_config())

    @classmethod
    def test_and_apply(cls, service='dhcp4', request=None):
        cfg = cls.build_dhcp4_config()
        client = cls.client()
        test = client.config_test(service, cfg)
        if not test.get('success'):
            write_audit(request, action='dhcp_config_test', module='dhcp', payload=cfg, result='failed', error_message=test.get('message', ''))
            return test
        set_result = client.config_set(service, cfg)
        if not set_result.get('success'):
            write_audit(request, action='dhcp_config_set', module='dhcp', payload=cfg, result='failed', error_message=set_result.get('message', ''))
            return set_result
        write_result = client.config_write(service)
        reload_result = client.config_reload(service)
        ok = write_result.get('success') and reload_result.get('success')
        result = {'success': ok, 'code': 'SUCCESS' if ok else 'KEA_APPLY_ERROR', 'message': '配置已测试并下发' if ok else '配置写入或重载失败', 'data': {'test': test, 'set': set_result, 'write': write_result, 'reload': reload_result}}
        write_audit(request, action='dhcp_config_apply', module='dhcp', payload=cfg, result='success' if ok else 'failed', error_message='' if ok else result['message'])
        return result

    @staticmethod
    @transaction.atomic
    def mark_reservation_ipam(reservation, user=None):
        if not reservation.dhcp_subnet.ipam_subnet_id:
            return None
        ip_obj = IPAddress.objects.filter(subnet=reservation.dhcp_subnet.ipam_subnet, ip_address=reservation.ip_address).first()
        if ip_obj:
            return IPAMService.set_status(ip_obj, 'dhcp_reserved', user, 'dhcp_reservation', hostname=reservation.hostname, mac_address=reservation.mac_address, dhcp_reservation=reservation)
        return None

    @staticmethod
    @transaction.atomic
    def release_reservation_ipam(reservation, user=None):
        ip_obj = IPAddress.objects.filter(dhcp_reservation=reservation).first()
        if ip_obj:
            return IPAMService.release(ip_obj, user)
        return None

    @classmethod
    @transaction.atomic
    def sync_leases(cls, request=None):
        leases = cls.read_mysql_leases()
        touched = 0
        active_ips = []
        for lease in leases:
            ip_address = lease.get('ip-address') or lease.get('address')
            if not ip_address:
                continue
            active_ips.append(str(ip_address))
            DHCPLease.objects.update_or_create(
                ip_address=ip_address,
                defaults={
                    'mac_address': lease.get('hw-address', ''),
                    'hostname': lease.get('hostname', ''),
                    'subnet_id': lease.get('subnet-id') or lease.get('subnet_id') or 0,
                    'state': str(lease.get('state', 'active')),
                    'valid_lifetime': lease.get('valid-lifetime'),
                    'expire_time': lease.get('expire-time'),
                    'updated_at': timezone.now(),
                },
            )
            ip_obj = IPAddress.objects.filter(ip_address=ip_address).first()
            if ip_obj and ip_obj.status == 'available':
                IPAMService.set_status(ip_obj, 'dhcp_dynamic', None, 'lease_sync', hostname=lease.get('hostname', ''), mac_address=lease.get('hw-address', ''))
            touched += 1
        expired_qs = DHCPLease.objects.exclude(ip_address__in=active_ips)
        expired_ips = list(expired_qs.values_list('ip_address', flat=True))
        expired_qs.update(state='expired')
        for ip_obj in IPAddress.objects.filter(status='dhcp_dynamic').exclude(ip_address__in=active_ips):
            IPAMService.set_status(ip_obj, 'available', None, 'lease_expired', **IPAMService.CLEAR_FIELDS)
        write_audit(request, action='dhcp_lease_sync', module='dhcp', payload={'leases': touched})
        return {'success': True, 'code': 'SUCCESS', 'message': 'Kea 租约同步完成', 'data': {'synced': touched, 'expired': len(expired_ips)}}

    @staticmethod
    def read_mysql_leases():
        connection = pymysql.connect(
            host=settings.KEA_LEASE_DB_HOST,
            port=settings.KEA_LEASE_DB_PORT,
            user=settings.KEA_LEASE_DB_USER,
            password=settings.KEA_LEASE_DB_PASSWORD,
            database=settings.KEA_LEASE_DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT address, hwaddr, client_id, valid_lifetime, expire, subnet_id, hostname, state
                    FROM lease4
                    WHERE state = 0
                    ORDER BY expire DESC
                    """
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        leases = []
        for row in rows:
            expire_time = row.get('expire')
            if expire_time and timezone.is_naive(expire_time):
                expire_time = timezone.make_aware(expire_time, timezone.get_current_timezone())
            leases.append({
                'ip-address': str(ipaddress.IPv4Address(row['address'])),
                'hw-address': DHCPService.format_hwaddr(row.get('hwaddr')),
                'client-id': DHCPService.format_client_id(row.get('client_id')),
                'valid-lifetime': row.get('valid_lifetime'),
                'expire-time': expire_time,
                'subnet-id': row.get('subnet_id') or 0,
                'hostname': row.get('hostname') or '',
                'state': 'active',
            })
        return leases

    @staticmethod
    def format_hwaddr(value):
        if not value:
            return ''
        return ':'.join(f'{byte:02x}' for byte in bytes(value))

    @staticmethod
    def format_client_id(value):
        if not value:
            return ''
        return bytes(value).hex()

    @staticmethod
    def release_lease(lease):
        address = int(ipaddress.IPv4Address(str(lease.ip_address)))
        connection = pymysql.connect(
            host=settings.KEA_LEASE_DB_HOST,
            port=settings.KEA_LEASE_DB_PORT,
            user=settings.KEA_LEASE_DB_USER,
            password=settings.KEA_LEASE_DB_PASSWORD,
            database=settings.KEA_LEASE_DB_NAME,
            charset='utf8mb4',
        )
        try:
            with connection.cursor() as cursor:
                deleted = cursor.execute('DELETE FROM lease4 WHERE address = %s', [address])
            connection.commit()
        finally:
            connection.close()
        lease.state = 'released'
        lease.save(update_fields=['state', 'updated_at'])
        ip_obj = IPAddress.objects.filter(ip_address=lease.ip_address, status='dhcp_dynamic').first()
        if ip_obj:
            IPAMService.set_status(ip_obj, 'available', None, 'dhcp_lease_release', **IPAMService.CLEAR_FIELDS)
        return {'success': True, 'code': 'SUCCESS', 'message': '租约已释放', 'data': {'deleted': deleted}}

    @classmethod
    def subnet_deploy_rows(cls, subnets):
        remote_map = cls.current_subnet_map()
        rows = []
        for subnet in subnets:
            local = cls.local_subnet_signature(subnet)
            remote = remote_map.get(subnet.subnet_id)
            deployed = bool(remote and cls.signatures_match(local, remote))
            rows.append({
                'subnet': subnet,
                'pool_count': subnet.pools.filter(status='enabled').count(),
                'reservation_count': DHCPReservation.objects.filter(
                    status='enabled',
                    dhcp_subnet=subnet,
                ).filter(Q(mac_address__gt='') | Q(client_id__gt='')).count(),
                'deploy_status': 'success' if deployed else 'pending-deploy',
                'deploy_label': '已下发' if deployed else '待下发',
                'deploy_detail': 'Kea 当前运行配置已一致' if deployed else cls.deploy_diff_text(local, remote),
            })
        return rows

    @classmethod
    def current_subnet_map(cls):
        result = cls.client().config_get('dhcp4')
        if not result.get('success'):
            return {}
        data = result.get('data') or []
        if isinstance(data, list) and data:
            arguments = data[0].get('arguments', {}) if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            arguments = data.get('arguments', data)
        else:
            arguments = {}
        dhcp4 = arguments.get('Dhcp4', arguments)
        remote = {}
        for subnet in dhcp4.get('subnet4', []) if isinstance(dhcp4, dict) else []:
            if isinstance(subnet, dict) and subnet.get('id') is not None:
                remote[int(subnet['id'])] = cls.remote_subnet_signature(subnet)
        return remote

    @classmethod
    def local_subnet_signature(cls, subnet):
        options = {}
        if subnet.gateway:
            options['routers'] = str(subnet.gateway)
        if subnet.dns_servers:
            options['domain-name-servers'] = subnet.dns_servers
        if subnet.domain_name:
            options['domain-name'] = subnet.domain_name
        return {
            'id': int(subnet.subnet_id),
            'subnet': str(ipaddress.ip_network(subnet.subnet, strict=False)),
            'interface': subnet.interface or '',
            'relay': str(subnet.relay_ip or ''),
            'pools': sorted(cls.normalize_pool(f'{p.pool_start} - {p.pool_end}') for p in subnet.pools.filter(status='enabled')),
            'options': options,
            'reservations': sorted(cls.reservation_signature(r) for r in subnet.reservations.filter(status='enabled') if cls.reservation_has_identifier(r)),
        }

    @classmethod
    def remote_subnet_signature(cls, subnet):
        options = {}
        for opt in subnet.get('option-data', []):
            name = opt.get('name')
            if name in ('routers', 'domain-name-servers', 'domain-name'):
                options[name] = opt.get('data', '')
        relay = subnet.get('relay') or {}
        relay_ips = relay.get('ip-addresses') or []
        return {
            'id': int(subnet.get('id')),
            'subnet': str(ipaddress.ip_network(subnet.get('subnet'), strict=False)),
            'interface': subnet.get('interface') or '',
            'relay': ','.join(str(ip) for ip in relay_ips),
            'pools': sorted(cls.normalize_pool(p.get('pool', '')) for p in subnet.get('pools', [])),
            'options': options,
            'reservations': sorted(cls.reservation_signature(r) for r in subnet.get('reservations', [])),
        }

    @staticmethod
    def normalize_pool(value):
        return (value or '').replace(' ', '')

    @staticmethod
    def reservation_signature(reservation):
        if isinstance(reservation, dict):
            return '|'.join([
                str(reservation.get('ip-address', '')),
                str(reservation.get('hw-address', '')).lower(),
                str(reservation.get('client-id', '')).lower(),
            ])
        return '|'.join([
            str(reservation.ip_address),
            (reservation.mac_address or '').lower(),
            (reservation.client_id or '').lower(),
        ])

    @staticmethod
    def signatures_match(local, remote):
        return local == remote

    @staticmethod
    def deploy_diff_text(local, remote):
        if not remote:
            return 'Kea 当前配置中未找到该子网'
        diffs = []
        for key, label in (('pools', '地址池'), ('options', 'Option'), ('reservations', '保留地址'), ('subnet', '子网'), ('interface', '接口'), ('relay', 'Relay 地址')):
            if local.get(key) != remote.get(key):
                diffs.append(label)
        return '配置差异：' + '、'.join(diffs) if diffs else '待确认'
