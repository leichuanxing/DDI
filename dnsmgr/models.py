"""
DNS管理模块 - 数据模型
定义DNS全局配置、区域、资源记录、探测任务、解析日志等
"""

from django.db import models
from django.conf import settings


class DNSSettings(models.Model):
    """DNS全局配置 - 单例模式，整个系统仅维护一份配置"""
    # 是否启用转发功能
    enable_forward = models.BooleanField('启用外部转发', default=True,
        help_text='启用后，本地无记录的域名将转发到上游DNS服务器查询')
    # 上游转发器地址列表，逗号分隔
    forwarders = models.CharField('外部转发DNS地址', max_length=500, default='8.8.8.8, 114.114.114.114',
        help_text='多个IP用逗号分隔，如: 8.8.8.8, 114.114.114.114')
    # 监听端口
    listen_port = models.IntegerField('监听端口', default=53, help_text='UDP监听端口，默认53')
    # 默认TTL
    default_ttl = models.IntegerField('默认TTL(秒)', default=3600)
    # 监听地址
    listen_address = models.GenericIPAddressField('监听地址', default='0.0.0.0',
        help_text='监听的网卡地址，0.0.0.0表示所有接口')
    # 缓存启用
    enable_cache = models.BooleanField('启用缓存', default=True,
        help_text='缓存外部查询结果，提高响应速度')
    # 缓存过期时间(秒)
    cache_ttl = models.IntegerField('缓存TTL(秒)', default=300,
        help_text='外部查询结果的缓存时间')

    class Meta:
        verbose_name = 'DNS设置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return 'DNS全局配置'

    @classmethod
    def get_settings(cls):
        """获取或创建单例配置 - 确保系统中始终存在且仅有一份配置"""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def get_forwarder_list(self):
        """获取转发器列表"""
        return [ip.strip() for ip in self.forwarders.split(',') if ip.strip()]


class DNSZone(models.Model):
    """DNS区域表 - 支持正向区域和反向区域"""
    ZONE_TYPE_CHOICES = (
        ('forward', '正向区域'),
        ('reverse', '反向区域'),
    )
    
    name = models.CharField('区域名称', max_length=255, unique=True)
    zone_type = models.CharField('区域类型', max_length=20, choices=ZONE_TYPE_CHOICES, default='forward')
    primary_dns = models.GenericIPAddressField('主DNS服务器', blank=True, null=True)
    description = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = 'DNS区域'
        verbose_name_plural = verbose_name
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_zone_type_display()})"
    
    @property
    def record_count(self):
        return self.records.count()
    
    @property
    def enabled_record_count(self):
        return self.records.filter(status='enabled').count()


class DNSRecord(models.Model):
    """DNS记录表 - 支持7种记录类型(A/AAAA/CNAME/PTR/MX/TXT/NS)，含探测端口和优先级"""
    RECORD_TYPE_CHOICES = (
        ('A', 'A (IPv4地址)'),
        ('AAAA', 'AAAA (IPv6地址)'),
        ('CNAME', 'CNAME (别名)'),
        ('PTR', 'PTR (指针)'),
        ('MX', 'MX (邮件交换)'),
        ('TXT', 'TXT (文本)'),
        ('NS', 'NS (名称服务器)'),
    )
    
    STATUS_CHOICES = (
        ('enabled', '启用'),
        ('disabled', '禁用'),
        ('invalid', '无效'),
    )
    
    name = models.CharField('记录名称', max_length=255)
    record_type = models.CharField('记录类型', max_length=10, choices=RECORD_TYPE_CHOICES, default='A')
    value = models.TextField('记录值')
    ttl = models.IntegerField('TTL(秒)', default=3600,
                              help_text='生存时间，默认3600秒(1小时)')
    zone = models.ForeignKey(DNSZone, on_delete=models.CASCADE, related_name='records',
                             verbose_name='所属区域')
    linked_ip = models.GenericIPAddressField('关联IP地址', protocol='both', 
                                             blank=True, null=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='enabled')
    probe_port = models.IntegerField('探测端口', blank=True, null=True,
                                    help_text='关联服务探测端口，创建时自动探测该IP:Port的可达性')  # 用于健康探测
    priority = models.IntegerField('优先级', default=0, blank=True, null=True,
                                   help_text='MX记录优先级')  # 同名同类记录按优先级选取最优
    description = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = 'DNS记录'
        verbose_name_plural = verbose_name
        ordering = ['name']
        # 同一区域内，记录名+类型+优先级组合唯一（允许同名称类型但不同优先级的记录共存）
        unique_together = [['zone', 'name', 'record_type', 'priority']]
    
    def __str__(self):
        return f"{self.name} {self.record_type} {self.value}"
    
    def get_ptr_suggestion(self):
        """获取PTR记录建议 - 根据A记录的关联IP自动生成反向解析域名"""
        if self.record_type == 'A' and self.linked_ip:
            from common.ip_utils import generate_ptr_record
            return generate_ptr_record(self.linked_ip)
        return ''
    
    def get_fqdn(self):
        """获取完整域名 - 将记录名与区域名拼接为FQDN"""
        if self.zone.zone_type == 'forward':
            if self.name.endswith(self.zone.name):
                return self.name
            return f"{self.name}.{self.zone.name}" if self.name != '@' else self.zone.name
        return self.name
    
    def enable(self):
        """启用记录"""
        self.status = 'enabled'
        self.save()
    
    def disable(self):
        """禁用记录"""
        self.status = 'disabled'
        self.save()


class ProbeTask(models.Model):
    """服务探测任务 - 持久化存储，由前端定时调度执行探测"""
    TASK_STATUS_CHOICES = (
        ('running', '运行中'),
        ('paused',  '已暂停'),
        ('stopped', '已停止'),
    )

    name        = models.CharField('任务名称', max_length=100)
    target      = models.CharField('目标地址', max_length=255)
    port        = models.IntegerField('端口')
    interval    = models.IntegerField('探测间隔(秒)', default=10)
    status      = models.CharField('运行状态', max_length=20, choices=TASK_STATUS_CHOICES,
                                   default='running')
    # 统计
    total_probes     = models.IntegerField('总探测次数', default=0)
    reachable_count  = models.IntegerField('可达次数',   default=0)
    timeout_count    = models.IntegerField('超时次数',   default=0)
    error_count      = models.IntegerField('异常次数',   default=0)
    # 最近一次结果
    last_status    = models.CharField('最近状态', max_length=20, blank=True, default='')
    last_latency   = models.FloatField('最近延迟(ms)', blank=True, null=True)
    last_message   = models.CharField('最近消息', max_length=200, blank=True, default='')
    # 历史记录（JSON，存最近30条状态）
    history       = models.TextField('历史记录', blank=True, default='[]',
                                     help_text='JSON数组，存最近30条探测结果摘要')  # 环形缓冲区

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   verbose_name='创建者', related_name='probe_tasks')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '探测任务'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.target}:{self.port})"

    def get_history_list(self):
        import json
        try:
            return json.loads(self.history) if self.history else []
        except (json.JSONDecodeError, TypeError):
            return []

    def set_history(self, hlist):
        import json
        self.history = json.dumps(hlist[-30:] if len(hlist) > 30 else hlist)


class DNSQueryLog(models.Model):
    """DNS解析记录查询日志 - 最大存储10000条，超出自动清理最旧记录"""
    SOURCE_CHOICES = (
        ('local', '本地解析'),
        ('forward', '外部转发'),
        ('cache', '缓存命中'),
        ('nxdomain', 'NXDOMAIN'),
        ('servfail', 'SERVFAIL'),
    )
    
    # 查询信息
    query_name = models.CharField('查询域名', max_length=255, db_index=True)
    query_type = models.CharField('查询类型', max_length=10, default='A')
    
    # 来源客户端
    client_ip = models.GenericIPAddressField('客户端IP', db_index=True)
    
    # 解析结果
    result_source = models.CharField('结果来源', max_length=20, choices=SOURCE_CHOICES,
                                     default='local', db_index=True)
    answer_data = models.TextField('响应数据', blank=True,  # JSON格式的answer摘要
                                  help_text='存储解析结果的IP/域名等信息')
    
    # 响应状态
    rcode = models.IntegerField('响应码', default=0,
                                help_text='0=NOERR, 3=NXDOMAIN, 2=SERVFAIL')
    
    # 耗时(毫秒)
    response_time_ms = models.FloatField('响应耗时(ms)', default=0)
    
    # 时间戳
    query_time = models.DateTimeField('查询时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'DNS解析日志'
        verbose_name_plural = verbose_name
        ordering = ['-query_time']
        indexes = [
            models.Index(fields=['-query_time']),
            models.Index(fields=['query_name']),
            models.Index(fields=['client_ip']),
            models.Index(fields=['result_source']),
            models.Index(fields=['query_type']),
        ]
    
    def __str__(self):
        return f"{self.query_name} [{self.query_type}] -> {self.get_result_source_display()}"

    @property
    def answer_summary(self):
        """获取答案摘要"""
        import json
        if not self.answer_data:
            return '-'
        try:
            data = json.loads(self.answer_data)
            return data.get('summary', str(data)[:100])
        except (json.JSONDecodeError, TypeError):
            return self.answer_data[:80]

    @classmethod
    def create_log(cls, **kwargs):
        """创建日志条目（自动清理超限数据 - 保留最新10000条）"""
        log_obj = cls.objects.create(**kwargs)
        # 保持最多10000条，超出则删除最旧的
        total = cls.objects.count()
        if total > 10000:
            oldest_ids = cls.objects.order_by('query_time')[:total - 10000].values_list('id', flat=True)
            cls.objects.filter(id__in=list(oldest_ids)).delete()
        return log_obj
