from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
import ipaddress


class AddressSpace(models.Model):
    name = models.CharField('地址空间名称', max_length=64, unique=True)
    code = models.CharField('地址空间编码', max_length=64, unique=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '地址空间'
        verbose_name_plural = '地址空间'

    def __str__(self):
        return self.name


class Subnet(models.Model):
    STATUS_CHOICES = [('enabled', '启用'), ('disabled', '停用'), ('planned', '规划中')]
    address_space = models.ForeignKey(AddressSpace, verbose_name='地址空间', related_name='subnets', on_delete=models.PROTECT)
    cidr = models.CharField('CIDR', max_length=64)
    gateway = models.GenericIPAddressField('网关', null=True, blank=True)
    netmask = models.CharField('掩码', max_length=64, blank=True)
    vlan_id = models.IntegerField('VLAN ID', null=True, blank=True)
    vlan_name = models.CharField('VLAN 名称', max_length=64, blank=True)
    location = models.CharField('位置', max_length=128, blank=True)
    usage_type = models.CharField('用途', max_length=64, blank=True)
    description = models.TextField('描述', blank=True)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='enabled')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '网段'
        verbose_name_plural = '网段'
        unique_together = ('address_space', 'cidr')

    def clean(self):
        try:
            net = ipaddress.ip_network(self.cidr, strict=False)
        except ValueError as exc:
            raise ValidationError({'cidr': f'CIDR 格式错误: {exc}'})
        self.cidr = str(net)
        self.netmask = str(net.netmask)
        for other in Subnet.objects.filter(address_space=self.address_space).exclude(pk=self.pk):
            if net.overlaps(ipaddress.ip_network(other.cidr, strict=False)):
                raise ValidationError({'cidr': f'网段与 {other.cidr} 冲突'})
        if self.gateway and ipaddress.ip_address(self.gateway) not in net:
            raise ValidationError({'gateway': '网关必须属于当前网段'})

    @property
    def network(self):
        return ipaddress.ip_network(self.cidr, strict=False)

    def __str__(self):
        return self.cidr


class IPAddress(models.Model):
    STATUS_CHOICES = [
        ('available', '可用'), ('used', '已使用'), ('reserved', '预留'),
        ('dhcp_dynamic', 'DHCP 动态分配'), ('dhcp_reserved', 'DHCP 固定分配'), ('disabled', '禁用'),
    ]
    subnet = models.ForeignKey(Subnet, verbose_name='网段', related_name='ip_addresses', on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField('IP 地址')
    hostname = models.CharField('主机名', max_length=255, blank=True)
    mac_address = models.CharField('MAC 地址', max_length=32, blank=True)
    status = models.CharField('状态', max_length=32, choices=STATUS_CHOICES, default='available')
    usage_type = models.CharField('用途', max_length=64, blank=True)
    owner = models.CharField('使用人', max_length=64, blank=True)
    department = models.CharField('部门', max_length=64, blank=True)
    description = models.TextField('描述', blank=True)
    dns_record = models.ForeignKey('dns.DNSRecord', verbose_name='DNS记录', null=True, blank=True, on_delete=models.SET_NULL)
    dhcp_reservation = models.ForeignKey('dhcp.DHCPReservation', verbose_name='DHCP保留地址', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'IP 地址'
        verbose_name_plural = 'IP 地址'
        unique_together = ('subnet', 'ip_address')
        indexes = [models.Index(fields=['ip_address']), models.Index(fields=['status'])]

    def clean(self):
        if ipaddress.ip_address(self.ip_address) not in self.subnet.network:
            raise ValidationError({'ip_address': 'IP 地址必须属于所属网段'})

    def __str__(self):
        return str(self.ip_address)


class IPAddressHistory(models.Model):
    ip_address = models.ForeignKey(IPAddress, verbose_name='IP 地址', related_name='histories', on_delete=models.CASCADE)
    action = models.CharField('动作', max_length=64)
    old_status = models.CharField('原状态', max_length=32, blank=True)
    new_status = models.CharField('新状态', max_length=32, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='操作人', null=True, blank=True, on_delete=models.SET_NULL)
    detail = models.JSONField('详情', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = 'IP 使用历史'
        verbose_name_plural = 'IP 使用历史'
        ordering = ['-created_at']
