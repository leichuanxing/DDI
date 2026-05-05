from django.db import models
class SystemConfig(models.Model):
    key = models.CharField('配置键', max_length=128, unique=True)
    value = models.JSONField('配置值', default=dict, blank=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = '系统配置'; verbose_name_plural = '系统配置'
class ServiceHealthCheck(models.Model):
    STATUS_CHOICES = [('normal','正常'),('abnormal','异常'),('unknown','未知')]
    service_name = models.CharField('服务名称', max_length=64)
    status = models.CharField('服务状态', max_length=16, choices=STATUS_CHOICES, default='unknown')
    ip_address = models.GenericIPAddressField('IP 地址', null=True, blank=True)
    port = models.IntegerField('端口', null=True, blank=True)
    checked_at = models.DateTimeField('最近检测时间', auto_now_add=True)
    response_time_ms = models.IntegerField('响应耗时', null=True, blank=True)
    error_message = models.TextField('错误信息', blank=True)
    details = models.JSONField('详情', default=dict, blank=True)
    class Meta: verbose_name = '服务健康检查'; verbose_name_plural = '服务健康检查'; ordering = ['-checked_at']
