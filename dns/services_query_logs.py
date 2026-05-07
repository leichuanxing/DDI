from datetime import timedelta

from django.utils import timezone

from .models import DNSQueryLog


class DNSQueryLogService:
    RETENTION_DAYS = 7

    @classmethod
    def retention_cutoff(cls):
        return timezone.now() - timedelta(days=cls.RETENTION_DAYS)

    @classmethod
    def cleanup_expired(cls):
        deleted, _ = DNSQueryLog.objects.filter(query_time__lt=cls.retention_cutoff()).delete()
        return deleted

    @classmethod
    def create(cls, **data):
        cls.cleanup_expired()
        if not data.get('query_time'):
            data['query_time'] = timezone.now()
        if not data.get('result'):
            rcode = (data.get('response_code') or '').upper()
            data['result'] = 'success' if rcode in {'NOERROR', '0'} else 'failed' if rcode else 'unknown'
        return DNSQueryLog.objects.create(**data)
