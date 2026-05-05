import logging
import requests
from django.conf import settings
logger = logging.getLogger(__name__)
class KeaClient:
    def __init__(self, api_url=None, timeout=5, auth=None):
        self.api_url = (api_url or settings.KEA_API_URL).rstrip('/')
        self.timeout = timeout
        self.auth = auth
    def command(self, command, service=None, arguments=None):
        payload = {'command': command}
        if service: payload['service'] = [service]
        if arguments is not None: payload['arguments'] = arguments
        try:
            resp = requests.post(self.api_url + '/', json=payload, timeout=self.timeout, auth=self.auth)
        except requests.RequestException as exc:
            logger.exception('Kea API request failed')
            return {'success': False, 'code': 'KEA_CONNECTION_ERROR', 'message': str(exc), 'data': {}}
        if resp.status_code >= 400:
            return {'success': False, 'code': 'KEA_API_ERROR', 'message': resp.text, 'data': {}}
        try: data = resp.json()
        except ValueError: data = {'raw': resp.text}
        kea_error = self._extract_kea_error(data)
        if kea_error:
            return {'success': False, 'code': 'KEA_COMMAND_ERROR', 'message': kea_error, 'data': data}
        return {'success': True, 'code': 'SUCCESS', 'message': '操作成功', 'data': data}

    @staticmethod
    def _extract_kea_error(data):
        responses = data if isinstance(data, list) else [data]
        messages = []
        for item in responses:
            if not isinstance(item, dict):
                continue
            result = item.get('result')
            if result not in (None, 0):
                messages.append(item.get('text') or item.get('message') or f'Kea result={result}')
        return '; '.join(messages)
    def test_connection(self): return self.list_commands()
    def list_commands(self): return self.command('list-commands')
    def status_get(self, service='dhcp4'): return self.command('status-get', service)
    def version_get(self, service='dhcp4'): return self.command('version-get', service)
    def config_get(self, service='dhcp4'): return self.command('config-get', service)
    def config_test(self, service, config): return self.command('config-test', service, config)
    def config_set(self, service, config): return self.command('config-set', service, config)
    def config_reload(self, service='dhcp4'): return self.command('config-reload', service)
    def config_write(self, service='dhcp4'): return self.command('config-write', service)
    def lease_get_all(self, service='dhcp4'): return self.command('lease4-get-all', service)
    def lease_del(self, ip_address, service='dhcp4'): return self.command('lease4-del', service, {'ip-address': ip_address})
    def reservation_add(self, reservation, service='dhcp4'): return self.command('reservation-add', service, reservation)
    def reservation_del(self, reservation, service='dhcp4'): return self.command('reservation-del', service, reservation)
