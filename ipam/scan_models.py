"""
IPAM 探测功能模型
支持 Ping 探测、端口扫描、ARP 扫描
"""

from django.db import models
from accounts.models import User
import json


class ScanTask(models.Model):
    """扫描任务表 - 记录每次扫描任务"""
    
    TASK_TYPE_CHOICES = (
        ('ping', 'Ping 探测'),
        ('port', '端口扫描'),
        ('arp', 'ARP 扫描'),
        ('full', '综合扫描'),
    )
    
    STATUS_CHOICES = (
        ('pending', '等待执行'),
        ('running', '正在执行'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    )
    
    name = models.CharField('任务名称', max_length=200)
    task_type = models.CharField('任务类型', max_length=20, choices=TASK_TYPE_CHOICES, default='ping')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # 扫描目标配置
    target_type = models.CharField('目标类型', max_length=20, 
                                   choices=(('subnet', '子网'), ('range', 'IP范围'), ('single', '单个IP')), 
                                   default='subnet')
    subnet = models.ForeignKey('Subnet', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='scan_tasks', verbose_name='目标子网')
    start_ip = models.GenericIPAddressField('起始IP', blank=True, null=True)
    end_ip = models.GenericIPAddressField('结束IP', blank=True, null=True)
    
    # Ping 配置
    ping_count = models.IntegerField('Ping次数', default=3, help_text='每个IP发送的ICMP包数量')
    ping_timeout = models.FloatField('超时时间(秒)', default=1.0)
    
    # 端口扫描配置
    ports = models.CharField('扫描端口', max_length=500, blank=True, default='22,80,443,3389',
                             help_text='逗号分隔，如: 22,80,443 或 1-1000')
    port_scan_type = models.CharField('扫描类型', max_length=20, 
                                      choices=(('connect', 'TCP连接'), ('syn', 'SYN扫描')), 
                                      default='connect')
    
    # 其他配置
    concurrent = models.IntegerField('并发数', default=50, help_text='同时扫描的主机数')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='scan_tasks', verbose_name='创建人')
    
    # 统计信息
    total_targets = models.IntegerField('总目标数', default=0)
    scanned_count = models.IntegerField('已扫描数', default=0)
    online_count = models.IntegerField('在线主机数', default=0)
    offline_count =models.IntegerField('离线主机数', default=0)
    
    # 时间记录
    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    completed_at = models.DateTimeField('完成时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    # 结果摘要
    notes = models.TextField('备注/错误信息', blank=True)
    
    class Meta:
        verbose_name = '扫描任务'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"[{self.get_task_type_display()}] {self.name}"
    
    @property
    def progress(self):
        """计算进度百分比"""
        if self.total_targets == 0:
            return 0
        return int((self.scanned_count / self.total_targets) * 100)
    
    @property
    def duration(self):
        """计算耗时"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds())
        return None
    
    def get_target_ips(self):
        """获取要扫描的IP列表"""
        import ipaddress
        
        if self.target_type == 'subnet' and self.subnet:
            network = ipaddress.ip_network(self.subnet.cidr, strict=False)
            return [str(ip) for ip in network.hosts()]
        elif self.target_type == 'range' and self.start_ip and self.end_ip:
            start = int(ipaddress.ip_address(self.start_ip))
            end = int(ipaddress.ip_address(self.end_ip))
            if start > end:
                start, end = end, start
            return [str(ipaddress.ip_address(i)) for i in range(start, end + 1)]
        elif self.target_type == 'single' and self.start_ip:
            return [str(self.start_ip)]
        return []


class ScanResult(models.Model):
    """单次扫描结果 - 记录每个IP的探测结果"""
    
    task = models.ForeignKey(ScanTask, on_delete=models.CASCADE, related_name='results',
                            verbose_name='所属任务')
    ip_address = models.GenericIPAddressField('IP地址')
    
    # Ping 结果
    is_online = models.BooleanField('是否在线', default=False)
    ping_success = models.BooleanField('Ping成功', default=False)
    ping_avg_time = models.FloatField('平均延迟(ms)', null=True, blank=True)
    ping_min_time = models.FloatField('最小延迟(ms)', null=True, blank=True)
    ping_max_time = models.FloatField('最大延迟(ms)', null=True, blank=True)
    packet_loss = models.FloatField('丢包率(%)', default=100.0)
    ttl = models.IntegerField('TTL', null=True, blank=True)
    
    # DNS 反解结果
    reverse_dns = models.CharField('反解域名', max_length=255, blank=True)
    
    # 端口扫描结果 (JSON格式存储开放端口及服务)
    open_ports = models.JSONField('开放端口', default=dict, blank=True)
    # 格式: {"22": {"state": "open", "service": "ssh"}, "80": {"state": "open", "service": "http"}}
    
    # ARP 结果
    mac_address = models.CharField('MAC地址', max_length=17, blank=True)
    vendor = models.CharField('厂商', max_length=100, blank=True)
    
    # 关联信息（自动匹配）
    matched_device = models.ForeignKey('devices.Device', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='scan_results', verbose_name='匹配设备')
    matched_ip_record = models.ForeignKey('IPAddress', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='scan_results', verbose_name='匹配IP记录')
    
    # 标记
    is_new_host = models.BooleanField('新发现主机', default=False, 
                                      help_text='系统中未登记的主机')
    status_conflict = models.BooleanField('状态冲突', default=False,
                                          help_text='系统显示离线但实际在线，或反之')
    
    # 时间
    scanned_at = models.DateTimeField('扫描时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '扫描结果'
        verbose_name_plural = verbose_name
        ordering = ['ip_address']
        unique_together = ['task', 'ip_address']
    
    def __str__(self):
        status = "在线" if self.is_online else "离线"
        return f"{self.ip_address} ({status})"


class DiscoveryRule(models.Model):
    """自动发现规则 - 定期或触发式扫描规则"""
    
    name = models.CharField('规则名称', max_length=200)
    subnet = models.ForeignKey('Subnet', on_delete=models.CASCADE, related_name='discovery_rules',
                              verbose_name='目标子网')
    
    scan_types = models.CharField('扫描类型', max_length=100, default='ping',
                                  help_text='逗号分隔: ping,port,arp')
    ports = models.CharField('端口', max_length=500, blank=True, default='22,80,443')
    
    SCHEDULE_CHOICES = (
        ('manual', '手动触发'),
        ('hourly', '每小时'),
        ('daily', '每天'),
        ('weekly', '每周'),
    )
    schedule = models.CharField('调度周期', max_length=20, choices=SCHEDULE_CHOICES, default='manual')
    
    is_active = models.BooleanField('启用', default=True)
    last_run = models.DateTimeField('上次执行', null=True, blank=True)
    next_run = models.DateTimeField('下次执行', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '发现规则'
        verbose_name_plural = verbose_name
    
    def __str__(self):
        return f"{self.name} -> {self.subnet}"


class ProbeHistory(models.Model):
    """探测历史 - 记录对单个IP的历史探测数据"""
    
    ip_address = models.GenericIPAddressField('IP地址', db_index=True)
    subnet = models.ForeignKey('Subnet', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='probe_history')
    
    is_online = models.BooleanField('是否在线')
    ping_time = models.FloatField('延迟(ms)', null=True, blank=True)
    mac_address = models.CharField('MAC地址', max_length=17, blank=True)
    open_ports = models.JSONField(default=list, blank=True)  # 开放端口列表
    
    source = models.CharField('来源', max_length=50, 
                              choices=(('task', '扫描任务'), ('manual', '手动探测'), ('schedule', '定时任务')),
                              default='manual')
    task = models.ForeignKey(ScanTask, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name='history_records')
    
    probed_at = models.DateTimeField('探测时间', db_index=True, auto_now_add=True)
    
    class Meta:
        verbose_name = '探测历史'
        verbose_name_plural = verbose_name
        ordering = ['-probed_at']
        indexes = [
            models.Index(fields=['ip_address', '-probed_at']),
        ]
    
    @classmethod
    def get_latest_status(cls, ip_address):
        """获取某个IP的最新在线状态"""
        latest = cls.objects.filter(ip_address=ip_address).order_by('-probed_at').first()
        if latest:
            return {
                'is_online': latest.is_online,
                'ping_time': latest.ping_time,
                'mac_address': latest.mac_address,
                'probed_at': latest.probed_at.isoformat(),
            }
        return None
