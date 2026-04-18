from django.db import models
from django.conf import settings


class OperationLog(models.Model):
    """操作日志"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             related_name='operation_logs', verbose_name='操作用户')
    module = models.CharField('操作模块', max_length=50)  # ipam, dns, dhcp, devices, accounts
    action = models.CharField('操作类型', max_length=50)  # 新增/修改/删除/导入/导出/登录/退出
    object_type = models.CharField('对象类型', max_length=50)
    old_value = models.TextField('变更前内容', blank=True)
    new_value = models.TextField('变更后内容', blank=True)
    ip_address = models.GenericIPAddressField('IP地址', blank=True, null=True)
    operation_time = models.DateTimeField('操作时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '操作日志'
        verbose_name_plural = verbose_name
        ordering = ['-operation_time']
    
    def __str__(self):
        return f"{self.user} {self.action} {self.object_type} @ {self.operation_time}"
