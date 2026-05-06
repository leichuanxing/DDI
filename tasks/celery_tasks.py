import traceback

from django.utils import timezone

from ddi_system.celery import app
from dhcp.models import DHCPLease
from dhcp.services import DHCPService
from dns.models import DNSRecord, DNSZone
from dns.services import DNSService
from system.services import HealthService

from ipam.probe import (
    NETWORK_PROBE_TASK_TYPE_SET,
    redact_sensitive_payload,
    run_network_probe_task,
)

from .models import SystemTask, TaskLog


@app.task(bind=True, time_limit=600, soft_time_limit=540)
def execute_system_task(self, task_id):
    task = SystemTask.objects.get(pk=task_id)
    task.status = 'running'
    task.started_at = timezone.now()
    task.celery_task_id = self.request.id
    task.save(update_fields=['status', 'started_at', 'celery_task_id', 'updated_at'])
    TaskLog.objects.create(
        task=task,
        level='info',
        message=f'开始执行任务 {task.task_type}',
        payload=redact_sensitive_payload(task.request_payload),
    )
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
        elif task_type in NETWORK_PROBE_TASK_TYPE_SET:
            result = run_network_probe_task(task_type, payload)
        else:
            result = {'success': False, 'code': 'UNSUPPORTED_TASK', 'message': f'不支持的任务类型: {task_type}', 'data': {}}
        task.response_payload = result
        task.status = 'success' if result.get('success') else 'failed'
        ok = bool(result.get('success'))
        err_text = (result.get('message') or '').strip() if isinstance(result.get('message'), str) else (result.get('message') or '')
        task.error_message = '' if ok else (err_text or '任务失败')
        log_msg = (result.get('message') or '').strip() if isinstance(result.get('message'), str) else ''
        if not log_msg:
            log_msg = '任务完成' if ok else '任务失败（未返回具体说明，请查看响应数据或联系管理员）'
        TaskLog.objects.create(
            task=task,
            level='info' if ok else 'error',
            message=log_msg,
            payload=result if isinstance(result, dict) else {'raw': str(result)},
        )
    except Exception as exc:
        task.status = 'failed'
        tb = traceback.format_exc()
        exc_msg = str(exc).strip() or type(exc).__name__
        task.error_message = exc_msg
        TaskLog.objects.create(
            task=task,
            level='error',
            message=exc_msg,
            payload={'traceback': tb[-8000:]},
        )
    finally:
        task.finished_at = timezone.now()
        task.save()
    return task.response_payload
