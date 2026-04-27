"""
设备管理模块 - 数据模型
定义设备（主机）及其网络接口，支持多网卡/IP关联/DNS联动
"""

from django.db import models
from accounts.models import User
from ipam.models import Region, IPAddress


class Device(models.Model):
    """主机/设备表"""
    DEVICE_TYPE_CHOICES = (
        ('server', '服务器'),
        ('pc', 'PC'),
        ('laptop', '笔记本'),
        ('printer', '打印机'),
        ('switch', '交换机'),
        ('router', '路由器'),
        ('firewall', '防火墙'),
        ('camera', '摄像头'),
        ('ap', '无线AP'),
        ('storage', '存储设备'),
        ('other', '其他'),
    )
    
    hostname = models.CharField('主机名', max_length=200, unique=True)
    device_name = models.CharField('设备名称', max_length=200, blank=True)
    device_type = models.CharField('设备类型', max_length=50, choices=DEVICE_TYPE_CHOICES, default='pc')
    manager = models.CharField('管理员', max_length=100, blank=True)
    department = models.CharField('部门', max_length=100, blank=True)
    mac_address = models.CharField('MAC地址', max_length=17, blank=True, unique=True, null=True)
    operating_system = models.CharField('操作系统', max_length=100, blank=True)
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='devices', verbose_name='所属区域')
    ip_address = models.ForeignKey(IPAddress, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='device', verbose_name='关联IP地址')
    description = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='创建人')
    
    class Meta:
        verbose_name = '设备'
        verbose_name_plural = verbose_name
        ordering = ['hostname']
    
    def __str__(self):
        return f"{self.hostname} ({self.get_device_type_display()})"


class DeviceInterface(models.Model):
    """设备网络接口（一个设备可能有多个网卡）"""
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='interfaces',
                               verbose_name='所属设备')
    name = models.CharField('接口名称', max_length=50)  # eth0, ens33 等
    mac_address = models.CharField('MAC地址', max_length=17, blank=True)
    ip_address = models.ForeignKey(IPAddress, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='interface', verbose_name='IP地址')
    is_primary = models.BooleanField('主接口', default=False)
    description = models.TextField('描述', blank=True)
    
    class Meta:
        verbose_name = '设备接口'
        verbose_name_plural = verbose_name
    
    def __str__(self):
        return f"{self.device.hostname} - {self.name}"
