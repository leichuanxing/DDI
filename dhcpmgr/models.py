"""
DHCP管理模块 - 数据模型
定义DHCP地址池、排除地址、租约等数据结构
"""

from django.db import models
from ipam.models import Subnet


class DHCPPool(models.Model):
    """DHCP地址池 - 定义IP分配范围、网关、DNS、租约时间等"""
    STATUS_CHOICES = (
        ('enabled', '启用'),
        ('disabled', '禁用'),
    )
    
    name = models.CharField('地址池名称', max_length=200)
    subnet = models.ForeignKey(Subnet, on_delete=models.CASCADE, related_name='dhcp_pools',
                               verbose_name='所属子网')
    start_address = models.GenericIPAddressField('起始地址')
    end_address = models.GenericIPAddressField('结束地址')
    gateway = models.GenericIPAddressField('网关', blank=True, null=True)
    dns_servers = models.CharField('DNS服务器', max_length=500, blank=True,
                                   help_text='多个DNS用逗号分隔')  # 如: 8.8.8.8, 114.114.114.114
    lease_time = models.IntegerField('租约时间(秒)', default=86400,
                                     help_text='默认86400秒(24小时)')  # 默认1天
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='enabled')
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = 'DHCP地址池'
        verbose_name_plural = verbose_name
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.start_address} - {self.end_address})"
    
    @property
    def total_addresses(self):
        """地址池总IP数"""
        import ipaddress
        start = int(ipaddress.ip_address(self.start_address))
        end = int(ipaddress.ip_address(self.end_address))
        return end - start + 1
    
    @property
    def allocated_count(self):
        """已分配数量"""
        return self.leases.filter(status='active').count()
    
    @property
    def available_count(self):
        """可用数量（排除保留地址后）"""
        import ipaddress
        # 计算所有排除地址段中的IP总数（避免重复）
        excluded_ips = set()
        for excl in self.exclusions.all():
            start = int(ipaddress.ip_address(excl.start_ip))
            end = int(ipaddress.ip_address(excl.end_ip))
            for i in range(start, end + 1):
                excluded_ips.add(i)
        return self.total_addresses - self.allocated_count - len(excluded_ips)
    
    def is_valid_range(self):
        """检查地址范围是否在子网内且起始<=结束"""
        from common.ip_utils import ip_in_network
        if not self.subnet:
            return False
        in_network = (ip_in_network(self.start_address, self.subnet.cidr) and 
                     ip_in_network(self.end_address, self.subnet.cidr))
        
        # 检查起始地址 <= 结束地址
        import ipaddress
        start = int(ipaddress.ip_address(self.start_address))
        end = int(ipaddress.ip_address(self.end_address))
        
        return in_network and start <= end


class DHCPExclusion(models.Model):
    """DHCP排除地址 - 地址池中不参与分配的IP范围"""
    pool = models.ForeignKey(DHCPPool, on_delete=models.CASCADE, related_name='exclusions',
                             verbose_name='所属地址池')
    start_ip = models.GenericIPAddressField('起始IP')
    end_ip = models.GenericIPAddressField('结束IP')
    reason = models.CharField('排除原因', max_length=200, blank=True)
    notes = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '排除地址'
        verbose_name_plural = verbose_name
        ordering = ['start_ip']
    
    def __str__(self):
        return f"{self.start_ip} - {self.end_ip} ({self.reason})"


class DHCPLease(models.Model):
    """DHCP租约 - 记录IP地址与MAC地址的绑定关系及租期"""
    STATUS_CHOICES = (
        ('active', '活跃'),
        ('expired', '过期'),
        ('released', '已释放'),
    )
    
    ip_address = models.GenericIPAddressField('IP地址')
    mac_address = models.CharField('MAC地址', max_length=17)
    hostname = models.CharField('主机名', max_length=200, blank=True)
    device_identifier = models.CharField('设备标识', max_length=200, blank=True)
    start_time = models.DateTimeField('租约开始时间')
    end_time = models.DateTimeField('租约结束时间')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    pool = models.ForeignKey(DHCPPool, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='leases', verbose_name='所属地址池')
    created_at = models.DateTimeField('记录时间', auto_now_add=True)

    class Meta:
        verbose_name = 'DHCP租约'
        verbose_name_plural = verbose_name
        ordering = ['-end_time']
        constraints = [
            models.UniqueConstraint(
                fields=['ip_address'],
                condition=models.Q(status='active'),
                name='unique_active_ip'
            )
        ]
    
    def __str__(self):
        return f"{self.ip_address} -> {self.mac_address}"
    
    @property
    def is_expired(self):
        """判断租约是否已过期（当前时间超过结束时间且状态仍为active）"""
        from django.utils import timezone
        return timezone.now() > self.end_time and self.status == 'active'
    
    def release(self):
        """释放租约 - 将状态置为released"""
        self.status = 'released'
        self.save()


class DHCPLog(models.Model):
    """DHCP客户端地址获取日志 - 记录每次DISCOVER/OFFER/REQUEST/ACK/NAK/RELEASE交互"""

    MSG_TYPE_CHOICES = (
        ('discover', 'DISCOVER'),
        ('offer', 'OFFER'),
        ('request', 'REQUEST'),
        ('ack', 'ACK'),
        ('nak', 'NAK'),
        ('release', 'RELEASE'),
    )

    STATUS_CHOICES = (
        ('success', '成功'),
        ('fail', '失败'),
        ('ignored', '忽略'),
    )

    msg_type = models.CharField('消息类型', max_length=20, choices=MSG_TYPE_CHOICES)
    mac_address = models.CharField('MAC地址', max_length=17)
    ip_address = models.GenericIPAddressField('分配IP地址', null=True, blank=True)
    client_addr = models.GenericIPAddressField('客户端来源IP')
    pool_name = models.CharField('地址池名称', max_length=200, blank=True)
    server_id = models.GenericIPAddressField('Server ID', null=True, blank=True)
    status = models.CharField('处理结果', max_length=20, choices=STATUS_CHOICES, default='success')
    detail = models.TextField('详情', blank=True, help_text='附加信息，如失败原因等')
    created_at = models.DateTimeField('记录时间', db_index=True, auto_now_add=True)

    class Meta:
        verbose_name = 'DHCP日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['mac_address']),
            models.Index(fields=['ip_address']),
            models.Index(fields=['msg_type']),
        ]

    def __str__(self):
        return f"[{self.created_at.strftime('%m-%d %H:%M:%S')}] {self.get_msg_type_display()} {self.mac_address} -> {self.ip_address or '-'} ({self.get_status_display()})"
