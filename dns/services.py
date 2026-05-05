from django.utils import timezone
from django.conf import settings
from urllib.parse import urlparse
from datetime import datetime

from common.audit import write_audit

from .clients import PowerDNSClient
from .models import DNSChangeLog, DNSProviderConfig, DNSRecord, DNSZone


class DNSService:
    @staticmethod
    def default_config_values():
        api_url = getattr(settings, 'PDNS_API_URL', 'http://ddi-pdns:8081')
        parsed = urlparse(api_url)
        return {
            'api_url': api_url,
            'api_port': parsed.port or 8081,
            'api_key': getattr(settings, 'PDNS_API_KEY', 'ddi-pdns-key'),
            'server_id': 'localhost',
            'timeout': 5,
            'use_ssl': parsed.scheme == 'https',
            'health_check_enabled': True,
        }

    @classmethod
    def ensure_config(cls):
        defaults = cls.default_config_values()
        cfg = DNSProviderConfig.objects.order_by('-id').first()
        if cfg:
            changed = False
            for field in ('api_url', 'api_port', 'api_key', 'server_id', 'use_ssl', 'health_check_enabled'):
                if not getattr(cfg, field):
                    setattr(cfg, field, defaults[field])
                    changed = True
            # In this four-container deployment ddi-web must manage PowerDNS through
            # the Docker service name, not through the host/browser address.
            if 'ddi-pdns' not in (cfg.api_url or ''):
                cfg.api_url = defaults['api_url']
                cfg.api_port = defaults['api_port']
                cfg.use_ssl = defaults['use_ssl']
                changed = True
            if changed:
                cfg.save()
            return cfg
        return DNSProviderConfig.objects.create(**defaults)

    @classmethod
    def reset_default_config(cls):
        defaults = cls.default_config_values()
        cfg = DNSProviderConfig.objects.order_by('-id').first()
        if cfg:
            for field, value in defaults.items():
                setattr(cfg, field, value)
            cfg.save()
            return cfg
        return DNSProviderConfig.objects.create(**defaults)

    @staticmethod
    def client():
        cfg = DNSService.ensure_config()
        return PowerDNSClient(cfg.api_url, cfg.api_key, cfg.server_id, cfg.timeout)

    @staticmethod
    def zone_payload(zone):
        return {
            'name': DNSService.canonical_zone_name(zone.name),
            'kind': zone.kind,
            'dnssec': zone.dnssec,
            'api_rectify': zone.api_rectify,
            'nameservers': [DNSService.default_nameserver(zone.name)],
        }

    @staticmethod
    def default_nameserver(zone_name=None):
        configured = getattr(settings, 'PDNS_DEFAULT_NAMESERVER', '')
        if configured:
            return configured if configured.endswith('.') else f'{configured}.'
        return 'ns1.devnets.net.'

    @staticmethod
    def soa_content(zone_name):
        ns = DNSService.default_nameserver(zone_name)
        serial = datetime.utcnow().strftime('%Y%m%d%H')
        return f'{ns} hostmaster.devnets.net. {serial} 10800 3600 604800 3600'

    @classmethod
    def ensure_zone_authority_records(cls, zone):
        zone_name = cls.canonical_zone_name(zone.name)
        client = cls.client()
        soa = client.update_record(zone_name, {
            'name': zone_name,
            'type': 'SOA',
            'ttl': 3600,
            'changetype': 'REPLACE',
            'records': [{'content': cls.soa_content(zone.name), 'disabled': False}],
        })
        ns = client.update_record(zone_name, {
            'name': zone_name,
            'type': 'NS',
            'ttl': 3600,
            'changetype': 'REPLACE',
            'records': [{'content': cls.default_nameserver(zone.name), 'disabled': False}],
        })
        return soa if not soa.get('success') else ns

    @staticmethod
    def record_rrset(record, changetype='REPLACE'):
        content = DNSService.canonical_record_content(record)
        return {
            'name': DNSService.canonical_record_name(record.name, record.zone.name),
            'type': record.record_type,
            'ttl': record.ttl,
            'changetype': changetype,
            'records': [{'content': content, 'disabled': record.disabled}],
        }

    @staticmethod
    def canonical_zone_name(name):
        value = (name or '').strip()
        return value if value.endswith('.') else f'{value}.'

    @staticmethod
    def canonical_record_name(name, zone_name):
        value = (name or '').strip()
        zone = DNSService.canonical_zone_name(zone_name)
        if value in ('', '@'):
            return zone
        if value.endswith('.'):
            return value
        if value == zone.rstrip('.') or value.endswith(f'.{zone.rstrip(".")}'):
            return f'{value}.'
        return f'{value}.{zone}'

    @staticmethod
    def canonical_record_content(record):
        content = (record.content or '').strip()
        if record.record_type in {'CNAME', 'NS', 'PTR'} and content and not content.endswith('.'):
            content = f'{content}.'
        if record.record_type == 'MX':
            if content and not content.endswith('.'):
                content = f'{content}.'
            return f'{record.priority or 10} {content}'
        return content

    @classmethod
    def push_zone(cls, zone, user=None, request=None):
        payload = cls.zone_payload(zone)
        result = cls.client().create_zone(payload)
        already_exists = result.get('status_code') in {409, 422} and 'exist' in (result.get('message', '').lower())
        ok = result.get('success') or already_exists
        if ok:
            zone.synced_at = timezone.now()
            zone.save(update_fields=['synced_at', 'updated_at'])
            authority_result = cls.ensure_zone_authority_records(zone)
            if not authority_result.get('success'):
                result = authority_result
                ok = False
            elif already_exists:
                result = {'success': True, 'code': 'SUCCESS', 'message': 'Zone 已存在于 PowerDNS', 'status_code': result.get('status_code'), 'data': result.get('data', {})}
        DNSChangeLog.objects.create(zone=zone, action='push_zone', payload=payload, result='success' if ok else 'failed', error_message='' if ok else result.get('message', ''), operator=user)
        write_audit(request, action='dns_zone_push', module='dns', obj=zone, payload=payload, result='success' if ok else 'failed', error_message=result.get('message', '') if not ok else '')
        return result

    @classmethod
    def delete_zone_remote(cls, zone, user=None, request=None):
        result = cls.client().delete_zone(cls.canonical_zone_name(zone.name))
        not_found = result.get('status_code') == 404
        ok = result.get('success') or not_found
        if not_found:
            result = {'success': True, 'code': 'SUCCESS', 'message': 'Zone 在 PowerDNS 中不存在，按已删除处理', 'status_code': 404, 'data': {}}
        DNSChangeLog.objects.create(zone=zone, action='delete_zone_remote', payload={'name': zone.name}, result='success' if ok else 'failed', error_message='' if ok else result.get('message', ''), operator=user)
        write_audit(request, action='dns_zone_delete_remote', module='dns', obj=zone, result='success' if ok else 'failed', error_message=result.get('message', '') if not ok else '')
        return result

    @classmethod
    def push_record(cls, record, changetype='REPLACE', user=None, request=None):
        payload = cls.record_rrset(record, changetype)
        result = cls.client().update_record(cls.canonical_zone_name(record.zone.name), payload)
        if result.get('success'):
            record.synced_at = timezone.now()
            record.save(update_fields=['synced_at', 'updated_at'])
        DNSChangeLog.objects.create(zone=record.zone, record=record, action=f'push_record_{changetype.lower()}', payload=payload, result='success' if result.get('success') else 'failed', error_message='' if result.get('success') else result.get('message', ''), operator=user)
        write_audit(request, action='dns_record_push', module='dns', obj=record, payload=payload, result='success' if result.get('success') else 'failed', error_message=result.get('message', '') if not result.get('success') else '')
        return result

    @classmethod
    def sync_zones(cls, request=None):
        result = cls.client().sync_zones()
        touched = 0
        if result.get('success'):
            for item in result.get('data') or []:
                DNSZone.objects.update_or_create(
                    name=cls.canonical_zone_name(item.get('name') or ''),
                    defaults={
                        'kind': item.get('kind', 'Native'),
                        'dnssec': item.get('dnssec', False),
                        'soa_edit_api': item.get('soa_edit_api', ''),
                        'api_rectify': item.get('api_rectify', False),
                        'synced_at': timezone.now(),
                    },
                )
                touched += 1
            DNSChangeLog.objects.create(action='sync_zones', payload={'zones': touched}, result='success')
        else:
            DNSChangeLog.objects.create(action='sync_zones', payload={}, result='failed', error_message=result.get('message', ''))
        write_audit(request, action='dns_zone_sync', module='dns', payload={}, result='success' if result.get('success') else 'failed', error_message=result.get('message', '') if not result.get('success') else '')
        return result

    @classmethod
    def sync_records(cls, zone, request=None):
        result = cls.client().sync_records(cls.canonical_zone_name(zone.name))
        if not result.get('success'):
            return result
        rrsets = (result.get('data') or {}).get('rrsets', [])
        touched = 0
        for rrset in rrsets:
            name = rrset.get('name')
            record_type = rrset.get('type')
            ttl = rrset.get('ttl') or 3600
            for record in rrset.get('records', []):
                DNSRecord.objects.update_or_create(
                    zone=zone,
                    name=name,
                    record_type=record_type,
                    content=record.get('content', ''),
                    defaults={'ttl': ttl, 'disabled': record.get('disabled', False), 'synced_at': timezone.now()},
                )
                touched += 1
        write_audit(request, action='dns_record_sync', module='dns', obj=zone, payload={'records': touched})
        return {'success': True, 'code': 'SUCCESS', 'message': 'DNS 记录同步完成', 'data': {'synced': touched}}

    @classmethod
    def sync_all_records(cls, request=None):
        zones = DNSZone.objects.filter(status='enabled').order_by('name')
        total = 0
        failures = []
        for zone in zones:
            result = cls.sync_records(zone, request)
            if result.get('success'):
                total += result.get('data', {}).get('synced', 0)
            else:
                failures.append({'zone': zone.name, 'message': result.get('message', '同步失败')})
        success = not failures
        DNSChangeLog.objects.create(
            action='sync_all_records',
            payload={'zones': zones.count(), 'records': total, 'failures': failures},
            result='success' if success else 'failed',
            error_message='; '.join(f"{item['zone']}: {item['message']}" for item in failures),
        )
        return {
            'success': success,
            'code': 'SUCCESS' if success else 'DNS_RECORD_SYNC_PARTIAL_FAILED',
            'message': 'DNS 记录同步完成' if success else '部分 DNS 记录同步失败',
            'data': {'zones': zones.count(), 'records': total, 'failures': failures},
        }

    @classmethod
    def compare_records(cls, zone=None):
        zones = [zone] if zone else DNSZone.objects.all()
        differences = []
        for item in zones:
            remote = cls.client().sync_records(item.name)
            if not remote.get('success'):
                differences.append({'zone': item.name, 'type': 'remote_error', 'message': remote.get('message')})
                continue
            remote_count = sum(len(rrset.get('records', [])) for rrset in (remote.get('data') or {}).get('rrsets', []))
            local_count = item.records.count()
            if local_count != remote_count:
                differences.append({'zone': item.name, 'type': 'count_mismatch', 'local': local_count, 'remote': remote_count})
        return {'success': True, 'code': 'SUCCESS', 'message': '差异比对完成', 'data': {'differences': differences}}
