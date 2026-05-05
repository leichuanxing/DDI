from django.utils import timezone

from ddi_system.celery import app
from dhcp.models import DHCPLease
from dhcp.services import DHCPService
from dns.models import DNSRecord, DNSZone
from dns.services import DNSService
from system.services import HealthService

from .models import SystemTask, TaskLog


@app.task(bind=True, time_limit=600, soft_time_limit=540)
def execute_system_task(self, task_id):
    task = SystemTask.objects.get(pk=task_id)
    task.status = 'running'
    task.started_at = timezone.now()
    task.celery_task_id = self.request.id
    task.save(update_fields=['status', 'started_at', 'celery_task_id', 'updated_at'])
    TaskLog.objects.create(task=task, level='info', message=f'开始执行任务 {task.task_type}', payload=task.request_payload)
    try:
        payload = task.request_payload or {}
        task_type = task.task_type
        if task_type == 'dns_zone_sync':
            result = DNSService.sync_zones()
        elif task_type == 'dns_zone_push':
            result = DNSService.push_zone(DNSZone.objects.get(pk=payload['zone_id']), task.created_by)
        elif task_type == 'dns_zone_delete':
            result = DNSService.delete_zone_remote(DNSZone.objects.get(pk=payload['zone_id']), task.created_by)
        elif task_type == 'dns_record_push':
            result = DNSService.push_record(DNSRecord.objects.get(pk=payload['record_id']), payload.get('changetype', 'REPLACE'), task.created_by)
        elif task_type == 'dns_record_sync':
            zone_id = payload.get('zone_id')
            result = DNSService.sync_records(DNSZone.objects.get(pk=zone_id)) if zone_id else DNSService.sync_all_records()
        elif task_type == 'dhcp_config_test':
            result = DHCPService.config_test(payload.get('service', 'dhcp4'))
        elif task_type == 'dhcp_config_apply':
            result = DHCPService.test_and_apply(payload.get('service', 'dhcp4'))
        elif task_type == 'dhcp_config_reload':
            result = DHCPService.client().config_reload(payload.get('service', 'dhcp4'))
        elif task_type == 'kea_lease_sync':
            result = DHCPService.sync_leases()
        elif task_type == 'dhcp_lease_release':
            lease = DHCPLease.objects.get(pk=payload['lease_id'])
            result = DHCPService.release_lease(lease)
        elif task_type == 'service_health_check':
            result = HealthService.check_all()
        else:
            result = {'success': False, 'code': 'UNSUPPORTED_TASK', 'message': f'不支持的任务类型: {task_type}', 'data': {}}
        task.response_payload = result
        task.status = 'success' if result.get('success') else 'failed'
        task.error_message = '' if result.get('success') else result.get('message', '')
        TaskLog.objects.create(task=task, level='info' if result.get('success') else 'error', message=result.get('message', '任务完成'), payload=result)
    except Exception as exc:
        task.status = 'failed'
        task.error_message = str(exc)
        TaskLog.objects.create(task=task, level='error', message=str(exc))
    finally:
        task.finished_at = timezone.now()
        task.save()
    return task.response_payload
