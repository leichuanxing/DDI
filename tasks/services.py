import os

from django.conf import settings

from .models import SystemTask
from .celery_tasks import execute_system_task


class TaskService:
    @staticmethod
    def ensure_broker_dirs():
        if not str(getattr(settings, 'CELERY_BROKER_URL', '')).startswith('filesystem://'):
            return
        for path in getattr(settings, 'CELERY_BROKER_TRANSPORT_OPTIONS', {}).values():
            if path:
                os.makedirs(path, exist_ok=True)

    @staticmethod
    def enqueue(task_type, target_service, payload=None, user=None):
        TaskService.ensure_broker_dirs()
        task = SystemTask.objects.create(task_type=task_type, target_service=target_service, request_payload=payload or {}, created_by=user)
        async_result = execute_system_task.delay(task.id)
        task.celery_task_id = async_result.id; task.save(update_fields=['celery_task_id'])
        return task
