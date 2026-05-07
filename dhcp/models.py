from django.db import models
from django.core.exceptions import ValidationError
import ipaddress
import re

from common.fields import EncryptedTextField


MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')

DHCP4_OPTION_NAMES = {
    1: 'subnet-mask',
    3: 'routers',
    6: 'domain-name-servers',
    12: 'host-name',
    15: 'domain-name',
    28: 'broadcast-address',
    32: 'router-solicitation-address',
    42: 'ntp-servers',
    51: 'dhcp-lease-time',
    66: 'tftp-server-name',
    67: 'boot-file-name',
    150: 'tftp-server-address',
}

DHCP4_IP_LIST_OPTIONS = {1, 3, 6, 28, 32, 42, 150}

class DHCPProviderConfig(models.Model):
    SERVICE_CHOICES = [('dhcp4', 'DHCPv4'), ('dhcp6', 'DHCPv6')]
    api_url = models.URLField('API 地址', default='http://ddi-kea:8000')
    api_port = models.IntegerField('API 端口', default=8000)
    service_type = models.CharField('服务类型', max_length=16, choices=SERVICE_CHOICES, default='dhcp4')
    timeout = models.IntegerField('连接超时时间', default=5)
    auth_enabled = models.BooleanField('启用认证', default=False)
    username = models.CharField('认证用户名', max_length=64, blank=True)
    password = EncryptedTextField('认证密码', blank=True)
    health_check_enabled = models.BooleanField('启用健康检查', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = 'Kea API 配置'; verbose_name_plural = 'Kea API 配置'
    def clean(self):
        if self.api_port < 1 or self.api_port > 65535:
            raise ValidationError({'api_port': 'API 端口必须在 1 到 65535 之间'})
        if self.timeout < 1 or self.timeout > 60:
            raise ValidationError({'timeout': '连接超时时间必须在 1 到 60 秒之间'})
        if self.auth_enabled and not (self.username and self.password):
            raise ValidationError('启用认证时必须填写认证用户名和认证密码')
    def __str__(self):
        return f'{self.api_url}:{self.api_port}'

class DHCPSubnet(models.Model):
    STATUS_CHOICES = [('enabled','启用'),('disabled','停用')]
    ipam_subnet = models.ForeignKey('ipam.Subnet', verbose_name='IPAM 网段', null=True, blank=True, on_delete=models.SET_NULL)
    subnet = models.CharField('子网', max_length=64)
    subnet_id = models.IntegerField('Kea 子网ID', unique=True)
    interface = models.CharField('接口', max_length=64, blank=True)
    relay_ip = models.GenericIPAddressField('Relay 地址', null=True, blank=True)
    gateway = models.GenericIPAddressField('网关', null=True, blank=True)
    dns_servers = models.CharField('DNS Server', max_length=255, blank=True)
    domain_name = models.CharField('Domain Name', max_length=255, blank=True)
    lease_time = models.IntegerField('租约时间', default=3600)
    valid_lifetime = models.IntegerField('有效生命周期', default=3600)
    renew_timer = models.IntegerField('续租时间', default=900)
    rebind_timer = models.IntegerField('重绑定时间', default=1800)
    description = models.TextField('描述', blank=True)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='enabled')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = 'DHCP 子网'; verbose_name_plural = 'DHCP 子网'
    def clean(self):
        try:
            network = ipaddress.ip_network(self.subnet, strict=False)
        except ValueError as exc:
            raise ValidationError({'subnet': f'子网格式错误: {exc}'})
        self.subnet = str(network)
        if self.gateway and ipaddress.ip_address(self.gateway) not in network:
            raise ValidationError({'gateway': '网关必须属于 DHCP 子网'})
    def __str__(self):
        label = f'{self.subnet} / ID {self.subnet_id}'
        if self.gateway:
            label += f' / GW {self.gateway}'
        return label

class DHCPPool(models.Model):
    dhcp_subnet = models.ForeignKey(DHCPSubnet, verbose_name='DHCP 子网', related_name='pools', on_delete=models.CASCADE)
    pool_start = models.GenericIPAddressField('起始地址')
    pool_end = models.GenericIPAddressField('结束地址')
    description = models.TextField('描述', blank=True)
    status = models.CharField('状态', max_length=16, default='enabled')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = 'DHCP 地址池'; verbose_name_plural = 'DHCP 地址池'
    def clean(self):
        if not self.dhcp_subnet_id or not self.pool_start or not self.pool_end:
            return
        network = ipaddress.ip_network(self.dhcp_subnet.subnet, strict=False)
        start_ip = ipaddress.ip_address(self.pool_start)
        end_ip = ipaddress.ip_address(self.pool_end)
        if start_ip > end_ip:
            raise ValidationError({'pool_start': '起始 IP 不能大于结束 IP'})
        if start_ip not in network or end_ip not in network:
            raise ValidationError('地址池不能超出所属 DHCP 子网')
        if self.dhcp_subnet.gateway:
            gateway = ipaddress.ip_address(self.dhcp_subnet.gateway)
            if start_ip <= gateway <= end_ip:
                raise ValidationError('地址池不能包含网关地址')
        for pool in self.dhcp_subnet.pools.exclude(pk=self.pk):
            old_start = ipaddress.ip_address(pool.pool_start)
            old_end = ipaddress.ip_address(pool.pool_end)
            if start_ip <= old_end and end_ip >= old_start:
                raise ValidationError(f'地址池与 {pool.pool_start}-{pool.pool_end} 重叠')
        for reservation in self.dhcp_subnet.reservations.filter(status='enabled'):
            reserved_ip = ipaddress.ip_address(reservation.ip_address)
            if start_ip <= reserved_ip <= end_ip:
                raise ValidationError(f'地址池包含已预留地址 {reservation.ip_address}')
    def __str__(self):
        return f'{self.dhcp_subnet.subnet}：{self.pool_start} - {self.pool_end}'

class DHCPReservation(models.Model):
    dhcp_subnet = models.ForeignKey(DHCPSubnet, verbose_name='DHCP 子网', related_name='reservations', on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField('IP 地址')
    mac_address = models.CharField('MAC 地址', max_length=32, blank=True)
    hostname = models.CharField('主机名', max_length=255, blank=True)
    client_id = models.CharField('Client ID', max_length=255, blank=True)
    description = models.TextField('描述', blank=True)
    status = models.CharField('状态', max_length=16, default='enabled')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = 'DHCP 保留地址'; verbose_name_plural = 'DHCP 保留地址'; unique_together = ('dhcp_subnet','ip_address')
    def clean(self):
        if self.mac_address:
            if not MAC_RE.match(self.mac_address):
                raise ValidationError({'mac_address': 'MAC 地址格式错误，示例：00:11:22:33:44:55'})
            self.mac_address = self.mac_address.lower().replace('-', ':')
        if not (self.mac_address or self.client_id):
            raise ValidationError('DHCP 保留地址必须填写 MAC 地址或 Client ID，否则 Kea 无法识别固定分配对象')
        if self.dhcp_subnet_id and self.ip_address:
            network = ipaddress.ip_network(self.dhcp_subnet.subnet, strict=False)
            if ipaddress.ip_address(self.ip_address) not in network:
                raise ValidationError({'ip_address': '保留地址必须属于 DHCP 子网'})
            qs = DHCPReservation.objects.filter(dhcp_subnet=self.dhcp_subnet, ip_address=self.ip_address).exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError('DHCP 保留地址重复')
            if self.mac_address and DHCPReservation.objects.filter(dhcp_subnet=self.dhcp_subnet, mac_address=self.mac_address).exclude(pk=self.pk).exists():
                raise ValidationError('同一子网下 MAC 地址已存在保留绑定')
            if self.client_id and DHCPReservation.objects.filter(dhcp_subnet=self.dhcp_subnet, client_id=self.client_id).exclude(pk=self.pk).exists():
                raise ValidationError('同一子网下 Client ID 已存在保留绑定')
    def __str__(self):
        host = f' / {self.hostname}' if self.hostname else ''
        return f'{self.ip_address}{host}'

class DHCPOption(models.Model):
    SCOPE_CHOICES = (
        ('global', '全局'),
        ('subnet', '子网'),
        ('pool', '地址池'),
    )

    scope_type = models.CharField('作用域类型', max_length=32, choices=SCOPE_CHOICES, default='global')
    scope_id = models.IntegerField('作用域ID', null=True, blank=True)
    option_code = models.IntegerField('Option Code')
    option_name = models.CharField('Option Name', max_length=64)
    option_value = models.TextField('Option Value')
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = 'DHCP Option'; verbose_name_plural = 'DHCP Option'
    def clean(self):
        if self.scope_type not in dict(self.SCOPE_CHOICES):
            raise ValidationError({'scope_type': '作用域类型必须为全局、子网或地址池'})
        if self.option_code < 1 or self.option_code > 255:
            raise ValidationError({'option_code': 'Option Code 必须在 1 到 255 之间'})
        self.option_name = (self.option_name or '').strip()
        self.option_value = (self.option_value or '').strip()
        if not self.option_name:
            raise ValidationError({'option_name': 'Option Name 不能为空'})
        if not self.option_value:
            raise ValidationError({'option_value': 'Option Value 不能为空'})
        expected_name = DHCP4_OPTION_NAMES.get(self.option_code)
        if expected_name and self.option_name != expected_name:
            raise ValidationError({'option_name': f'Option Code {self.option_code} 对应名称应为 {expected_name}'})
        if self.option_code in DHCP4_IP_LIST_OPTIONS:
            for item in re.split(r'\s*,\s*', self.option_value):
                try:
                    ipaddress.ip_address(item)
                except ValueError:
                    raise ValidationError({'option_value': f'Option {self.option_name} 的值必须是 IP 地址，多个地址用英文逗号分隔'})
        if self.scope_type == 'global':
            self.scope_id = None
        elif not self.scope_id:
            raise ValidationError({'scope_id': '子网或地址池作用域必须填写作用域对象'})
        elif self.scope_type == 'subnet' and not DHCPSubnet.objects.filter(pk=self.scope_id).exists():
            raise ValidationError({'scope_id': '选择的 DHCP 子网不存在'})
        elif self.scope_type == 'pool' and not DHCPPool.objects.filter(pk=self.scope_id).exists():
            raise ValidationError({'scope_id': '选择的 DHCP 地址池不存在'})
        duplicate = DHCPOption.objects.filter(
            scope_type=self.scope_type,
            scope_id=self.scope_id,
            option_code=self.option_code,
        ).exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError('同一作用域下 Option Code 不能重复')
    def __str__(self):
        return f'{self.option_name}({self.option_code}) = {self.option_value}'

class DHCPLease(models.Model):
    ip_address = models.GenericIPAddressField('IP 地址')
    mac_address = models.CharField('MAC 地址', max_length=32, blank=True)
    hostname = models.CharField('主机名', max_length=255, blank=True)
    subnet_id = models.IntegerField('子网ID')
    state = models.CharField('状态', max_length=32, blank=True)
    valid_lifetime = models.IntegerField('有效生命周期', null=True, blank=True)
    expire_time = models.DateTimeField('过期时间', null=True, blank=True)
    cltt = models.DateTimeField('CLTT', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta: verbose_name = 'DHCP 租约'; verbose_name_plural = 'DHCP 租约'; indexes = [models.Index(fields=['ip_address']), models.Index(fields=['mac_address'])]
    def __str__(self):
        return f'{self.ip_address} / {self.mac_address or "-"}'
