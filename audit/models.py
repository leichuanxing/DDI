from django.db import models
class AuditLog(models.Model):
    username = models.CharField('用户名', max_length=150, blank=True)
    user_id = models.IntegerField('用户ID', null=True, blank=True)
    action = models.CharField('动作', max_length=64)
    module = models.CharField('模块', max_length=64)
    object_type = models.CharField('对象类型', max_length=64, blank=True)
    object_id = models.CharField('对象ID', max_length=64, blank=True)
    object_name = models.CharField('对象名称', max_length=255, blank=True)
    request_ip = models.GenericIPAddressField('请求IP', null=True, blank=True)
    request_method = models.CharField('请求方法', max_length=16, blank=True)
    request_path = models.CharField('请求路径', max_length=512, blank=True)
    request_payload = models.JSONField('请求内容', default=dict, blank=True)
    response_status = models.IntegerField('响应状态', null=True, blank=True)
    result = models.CharField('结果', max_length=16, default='success')
    error_message = models.TextField('错误信息', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    class Meta: verbose_name = '审计日志'; verbose_name_plural = '审计日志'; ordering = ['-created_at']
