from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    """角色表"""
    ROLE_CHOICES = (
        ('admin', '系统管理员'),
        ('network_admin', '网络管理员'),
        ('operator', '运维人员'),
        ('auditor', '审计用户'),
    )
    
    name = models.CharField('角色名称', max_length=50, unique=True)
    code = models.CharField('角色编码', max_length=50, choices=ROLE_CHOICES, unique=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '角色'
        verbose_name_plural = verbose_name
    
    def __str__(self):
        return self.name


class User(AbstractUser):
    """扩展用户表"""
    
    ROLE_CHOICES = (
        ('admin', '系统管理员'),
        ('network_admin', '网络管理员'),
        ('operator', '运维人员'),
        ('auditor', '审计用户'),
    )
    
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True, verbose_name='角色')
    real_name = models.CharField('姓名', max_length=50, blank=True)
    phone = models.CharField('手机号', max_length=20, blank=True)
    department = models.CharField('部门', max_length=100, blank=True)
    is_active = models.BooleanField('状态', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    last_login_ip = models.GenericIPAddressField('最后登录IP', blank=True, null=True)
    
    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        ordering = ['-date_joined']
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    def get_role_display(self):
        if self.role:
            return self.role.name
        return '未分配'


class LoginLog(models.Model):
    """登录日志"""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='用户')
    username = models.CharField('用户名', max_length=150)
    ip_address = models.GenericIPAddressField('登录IP')
    user_agent = models.TextField('用户代理', blank=True)
    status = models.CharField('结果', max_length=20, default='success')  # success/failed
    message = models.CharField('消息', max_length=255, blank=True)
    login_time = models.DateTimeField('登录时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '登录日志'
        verbose_name_plural = verbose_name
        ordering = ['-login_time']
    
    def __str__(self):
        return f"{self.username} - {self.login_time}"
