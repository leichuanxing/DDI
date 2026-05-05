import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

class PowerDNSClient:
    def __init__(self, api_url=None, api_key=None, server_id='localhost', timeout=5):
        self.api_url = (api_url or settings.PDNS_API_URL).rstrip('/')
        self.api_key = api_key or settings.PDNS_API_KEY
        self.server_id = server_id
        self.timeout = timeout

    @property
    def headers(self):
        return {'X-API-Key': self.api_key, 'Content-Type': 'application/json'}

    def _request(self, method, path, **kwargs):
        url = f'{self.api_url}{path}'
        try:
            resp = requests.request(method, url, headers=self.headers, timeout=self.timeout, **kwargs)
            if resp.status_code >= 400:
                return {'success': False, 'code': 'PDNS_API_ERROR', 'message': resp.text, 'status_code': resp.status_code, 'data': {}}
            if resp.content:
                try: data = resp.json()
                except ValueError: data = {'raw': resp.text}
            else: data = {}
            return {'success': True, 'code': 'SUCCESS', 'message': '操作成功', 'status_code': resp.status_code, 'data': data}
        except requests.RequestException as exc:
            logger.exception('PowerDNS API request failed')
            return {'success': False, 'code': 'PDNS_CONNECTION_ERROR', 'message': str(exc), 'data': {}}

    def test_connection(self): return self._request('GET', '/api/v1/servers')
    def get_server_info(self): return self._request('GET', f'/api/v1/servers/{self.server_id}')
    def list_zones(self): return self._request('GET', f'/api/v1/servers/{self.server_id}/zones')
    def get_zone(self, zone_name): return self._request('GET', f'/api/v1/servers/{self.server_id}/zones/{zone_name}')
    def create_zone(self, zone_data): return self._request('POST', f'/api/v1/servers/{self.server_id}/zones', json=zone_data)
    def update_zone(self, zone_name, zone_data): return self._request('PUT', f'/api/v1/servers/{self.server_id}/zones/{zone_name}', json=zone_data)
    def delete_zone(self, zone_name): return self._request('DELETE', f'/api/v1/servers/{self.server_id}/zones/{zone_name}')
    def list_records(self, zone_name): return self.get_zone(zone_name)
    def create_record(self, zone_name, record_data): return self.update_record(zone_name, record_data)
    def update_record(self, zone_name, record_data): return self._request('PATCH', f'/api/v1/servers/{self.server_id}/zones/{zone_name}', json={'rrsets': [record_data]})
    def delete_record(self, zone_name, record_name, record_type): return self.update_record(zone_name, {'name': record_name, 'type': record_type, 'changetype': 'DELETE', 'records': []})
    def sync_zones(self): return self.list_zones()
    def sync_records(self, zone_name): return self.list_records(zone_name)
