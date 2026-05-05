from django.contrib.auth.models import AbstractUser
from django.db import models


class Permission(models.Model):
    module = models.CharField('模块', max_length=64)
    action = models.CharField('动作', max_length=64)
    code = models.CharField('权限编码', max_length=128, unique=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '权限'
        verbose_name_plural = '权限'
        ordering = ['module', 'action']

    def __str__(self):
        return self.code


class Role(models.Model):
    name = models.CharField('角色名称', max_length=64, unique=True)
    code = models.CharField('角色编码', max_length=64, unique=True)
    description = models.TextField('描述', blank=True)
    permissions = models.ManyToManyField(Permission, through='RolePermission', related_name='roles', verbose_name='权限')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '角色'
        verbose_name_plural = '角色'
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    real_name = models.CharField('真实姓名', max_length=64, blank=True)
    mobile = models.CharField('手机号', max_length=32, blank=True)
    roles = models.ManyToManyField(Role, through='UserRole', related_name='users', verbose_name='角色')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'


class UserRole(models.Model):
    user = models.ForeignKey(User, verbose_name='用户', on_delete=models.CASCADE)
    role = models.ForeignKey(Role, verbose_name='角色', on_delete=models.CASCADE)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '用户角色'
        verbose_name_plural = '用户角色'
        unique_together = ('user', 'role')


class RolePermission(models.Model):
    role = models.ForeignKey(Role, verbose_name='角色', on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, verbose_name='权限', on_delete=models.CASCADE)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '角色权限'
        verbose_name_plural = '角色权限'
        unique_together = ('role', 'permission')


class LoginLog(models.Model):
    username = models.CharField('用户名', max_length=150)
    user = models.ForeignKey(User, verbose_name='用户', null=True, blank=True, on_delete=models.SET_NULL)
    request_ip = models.GenericIPAddressField('请求IP', null=True, blank=True)
    user_agent = models.TextField('User Agent', blank=True)
    result = models.CharField('结果', max_length=16, default='success')
    error_message = models.TextField('错误信息', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '登录日志'
        verbose_name_plural = '登录日志'
        ordering = ['-created_at']
