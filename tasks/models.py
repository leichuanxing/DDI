from django.conf import settings
from django.db import models

class SystemTask(models.Model):
    STATUS_CHOICES = [('pending','等待执行'),('running','执行中'),('success','成功'),('failed','失败'),('canceled','已取消')]
    task_type = models.CharField('任务类型', max_length=64)
    target_service = models.CharField('目标服务', max_length=64)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    request_payload = models.JSONField('请求内容', default=dict, blank=True)
    response_payload = models.JSONField('响应内容', default=dict, blank=True)
    error_message = models.TextField('错误信息', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='创建人', null=True, blank=True, on_delete=models.SET_NULL)
    celery_task_id = models.CharField('Celery 任务ID', max_length=255, blank=True)
    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    finished_at = models.DateTimeField('结束时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = '系统任务'; verbose_name_plural = '系统任务'; ordering = ['-created_at']

class TaskLog(models.Model):
    task = models.ForeignKey(SystemTask, verbose_name='任务', related_name='logs', on_delete=models.CASCADE)
    level = models.CharField('级别', max_length=16, default='info')
    message = models.TextField('日志内容')
    payload = models.JSONField('附加数据', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    class Meta: verbose_name = '任务日志'; verbose_name_plural = '任务日志'; ordering = ['created_at']
