import os
import socket
import time

from django.db import connection

from dhcp.services import DHCPService
from dns.services import DNSService

from .models import ServiceHealthCheck


class HealthService:
    @staticmethod
    def _record(name, status, port=None, start=None, error='', details=None, ip_address=None):
        ms = int((time.monotonic() - start) * 1000) if start else None
        ServiceHealthCheck.objects.create(service_name=name, status=status, ip_address=ip_address, port=port, response_time_ms=ms, error_message=error, details=details or {})
        return {'service_name': name, 'status': status, 'ip_address': ip_address, 'port': port, 'response_time_ms': ms, 'error_message': error, 'details': details or {}}

    @staticmethod
    def _resolve(host):
        try:
            return socket.gethostbyname(host)
        except OSError:
            return None

    @classmethod
    def check_tcp(cls, name, host, port):
        start = time.monotonic()
        ip = cls._resolve(host)
        try:
            with socket.create_connection((host, port), timeout=3):
                return cls._record(name, 'normal', port, start, ip_address=ip)
        except Exception as exc:
            return cls._record(name, 'abnormal', port, start, str(exc), ip_address=ip)

    @classmethod
    def check_mysql(cls):
        start = time.monotonic()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
            return cls._record('ddi-web -> ddi-mysql', 'normal', int(os.getenv('MYSQL_PORT', '3306')), start, ip_address=cls._resolve(os.getenv('MYSQL_HOST', 'ddi-mysql')))
        except Exception as exc:
            return cls._record('ddi-web -> ddi-mysql', 'abnormal', int(os.getenv('MYSQL_PORT', '3306')), start, str(exc), ip_address=cls._resolve(os.getenv('MYSQL_HOST', 'ddi-mysql')))

    @classmethod
    def check_pdns_api(cls):
        start = time.monotonic()
        result = DNSService.client().test_connection()
        return cls._record('ddi-web -> ddi-pdns API', 'normal' if result.get('success') else 'abnormal', 8081, start, '' if result.get('success') else result.get('message', ''), result, cls._resolve('ddi-pdns'))

    @classmethod
    def check_kea_api(cls):
        start = time.monotonic()
        result = DHCPService.client().test_connection()
        return cls._record('ddi-web -> ddi-kea API', 'normal' if result.get('success') else 'abnormal', 8000, start, '' if result.get('success') else result.get('message', ''), result, cls._resolve('ddi-kea'))

    @classmethod
    def check_all(cls):
        data = [
            cls._record('ddi-web', 'normal', 8000, time.monotonic(), ip_address=cls._resolve('ddi-web')),
            cls.check_mysql(),
            cls.check_pdns_api(),
            cls.check_kea_api(),
            cls.check_tcp('ddi-pdns -> ddi-mysql', os.getenv('MYSQL_HOST', 'ddi-mysql'), int(os.getenv('MYSQL_PORT', '3306'))),
            cls.check_tcp('ddi-kea -> ddi-mysql', os.getenv('MYSQL_HOST', 'ddi-mysql'), int(os.getenv('MYSQL_PORT', '3306'))),
        ]
        return {'success': True, 'code': 'SUCCESS', 'message': '健康检查完成', 'data': data}
