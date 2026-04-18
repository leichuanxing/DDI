from django.db import models
from accounts.models import User


class Region(models.Model):
    """区域表 - 用于区分不同机房、园区、楼层、分支机构"""
    name = models.CharField('区域名称', max_length=100, unique=True)
    code = models.CharField('区域编码', max_length=50, unique=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = '区域'
        verbose_name_plural = verbose_name
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    @property
    def subnet_count(self):
        return self.subnets.count()
    
    @property
    def vlan_count(self):
        return self.vlans.count()


class VLAN(models.Model):
    """VLAN表"""
    vlan_id = models.IntegerField('VLAN ID', unique=True)
    name = models.CharField('VLAN名称', max_length=100)
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='vlans', verbose_name='所属区域')
    purpose = models.CharField('用途', max_length=200, blank=True)
    gateway = models.GenericIPAddressField('网关地址', blank=True, null=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = 'VLAN'
        verbose_name_plural = verbose_name
        ordering = ['vlan_id']
    
    def __str__(self):
        return f"VLAN {self.vlan_id} - {self.name}"


class Subnet(models.Model):
    """子网管理"""
    PURPOSE_CHOICES = (
        ('office', '办公网'),
        ('server', '服务器网'),
        ('monitor', '监控网'),
        ('guest', '访客网'),
        ('management', '管理网'),
        ('storage', '存储网'),
        ('dmz', 'DMZ区'),
        ('other', '其他'),
    )
    
    name = models.CharField('子网名称', max_length=200)
    cidr = models.CharField('网段地址', max_length=50, unique=True)
    gateway = models.GenericIPAddressField('网关地址', blank=True, null=True)
    prefix_len = models.IntegerField('掩码位数')
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='subnets', verbose_name='所属区域')
    vlan = models.ForeignKey(VLAN, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name='subnets', verbose_name='所属VLAN')
    purpose = models.CharField('用途', max_length=50, choices=PURPOSE_CHOICES, default='other')
    description = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = '子网'
        verbose_name_plural = verbose_name
        ordering = ['cidr']
    
    def __str__(self):
        return f"{self.name} ({self.cidr})"
    
    @property
    def total_ips(self):
        """总IP数"""
        from common.ip_utils import get_network_info
        info = get_network_info(self.cidr)
        return info['num_addresses'] - 2  # 减去网络地址和广播地址
    
    @property
    def allocated_ips(self):
        """已分配IP数"""
        return self.ip_addresses.filter(status='allocated').count()
    
    @property
    def available_ips(self):
        """空闲IP数"""
        from common.ip_utils import get_network_info
        info = get_network_info(self.cidr)
        total = info['num_addresses'] - 2
        used = self.ip_addresses.exclude(status='available').exclude(status='disabled').count()
        return total - used
    
    @property
    def usage_percent(self):
        """使用率百分比"""
        total = self.total_ips
        if total == 0:
            return 0
        return round((self.allocated_ips / total) * 100, 1)


class IPAddress(models.Model):
    """IP地址管理"""
    STATUS_CHOICES = (
        ('available', '空闲'),
        ('allocated', '已分配'),
        ('reserved', '保留'),
        ('conflict', '冲突'),
        ('disabled', '禁用'),
    )
    
    BINDING_TYPE_CHOICES = (
        ('static', '静态绑定'),
        ('dhcp', 'DHCP分配'),
    )
    
    ip_address = models.GenericIPAddressField('IP地址', protocol='both')
    subnet = models.ForeignKey(Subnet, on_delete=models.CASCADE, related_name='ip_addresses',
                               verbose_name='所属子网')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='available')
    hostname = models.CharField('主机名', max_length=200, blank=True)
    mac_address = models.CharField('MAC地址', max_length=17, blank=True)
    device_name = models.CharField('设备名称', max_length=200, blank=True)
    owner = models.CharField('使用人', max_length=100, blank=True)
    department = models.CharField('部门', max_length=100, blank=True)
    device_type = models.CharField('设备类型', max_length=50, blank=True)
    binding_type = models.CharField('绑定方式', max_length=20, choices=BINDING_TYPE_CHOICES, 
                                    default='static')
    dns_linked = models.BooleanField('DNS关联状态', default=False)
    notes = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='created_ips', verbose_name='创建人')
    
    class Meta:
        verbose_name = 'IP地址'
        verbose_name_plural = verbose_name
        unique_together = ['ip_address', 'subnet']
        ordering = ['ip_address']
    
    def __str__(self):
        return f"{self.ip_address} ({self.get_status_display()})"
    
    def allocate(self, **kwargs):
        """分配IP"""
        self.status = 'allocated'
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()
    
    def release(self):
        """释放IP"""
        self.status = 'available'
        self.hostname = ''
        self.mac_address = ''
        self.device_name = ''
        self.owner = ''
        self.department = ''
        self.device_type = ''
        self.binding_type = 'static'
        self.notes = ''
        self.save()
