from django.conf import settings
from django.db import models
from common.fields import EncryptedTextField

class DNSProviderConfig(models.Model):
    api_url = models.URLField('API 地址', default='http://ddi-pdns:8081')
    api_port = models.IntegerField('API 端口', default=8081)
    api_key = EncryptedTextField('API Key', blank=True)
    server_id = models.CharField('Server ID', max_length=64, default='localhost')
    timeout = models.IntegerField('连接超时时间', default=5)
    use_ssl = models.BooleanField('启用 SSL', default=False)
    health_check_enabled = models.BooleanField('启用健康检查', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta:
        verbose_name = 'PowerDNS API 配置'
        verbose_name_plural = 'PowerDNS API 配置'

class DNSZone(models.Model):
    KIND_CHOICES = [('Native','Native'),('Master','Master'),('Slave','Slave')]
    STATUS_CHOICES = [('enabled','启用'),('disabled','停用')]
    name = models.CharField('Zone 名称', max_length=255, unique=True)
    kind = models.CharField('类型', max_length=16, choices=KIND_CHOICES, default='Native')
    dnssec = models.BooleanField('DNSSEC', default=False)
    soa_edit_api = models.CharField('SOA Edit API', max_length=64, blank=True)
    api_rectify = models.BooleanField('API Rectify', default=False)
    description = models.TextField('描述', blank=True)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='enabled')
    synced_at = models.DateTimeField('同步时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta:
        verbose_name = 'DNS Zone'
        verbose_name_plural = 'DNS Zone'
    def __str__(self): return self.name

class DNSRecord(models.Model):
    TYPE_CHOICES = [(x,x) for x in ['A','AAAA','CNAME','MX','TXT','NS','PTR','SRV','CAA']]
    zone = models.ForeignKey(DNSZone, verbose_name='Zone', related_name='records', on_delete=models.CASCADE)
    name = models.CharField('记录名称', max_length=255)
    record_type = models.CharField('记录类型', max_length=16, choices=TYPE_CHOICES)
    content = models.CharField('记录内容', max_length=1024)
    ttl = models.IntegerField('TTL', default=3600)
    priority = models.IntegerField('优先级', null=True, blank=True)
    disabled = models.BooleanField('禁用', default=False)
    comment = models.TextField('备注', blank=True)
    synced_at = models.DateTimeField('同步时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta:
        verbose_name = 'DNS 记录'
        verbose_name_plural = 'DNS 记录'
        indexes = [models.Index(fields=['record_type']), models.Index(fields=['name'])]
    def __str__(self): return f'{self.name} {self.record_type} {self.content}'

class DNSChangeLog(models.Model):
    zone = models.ForeignKey(DNSZone, verbose_name='Zone', null=True, blank=True, on_delete=models.SET_NULL)
    record = models.ForeignKey(DNSRecord, verbose_name='记录', null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField('动作', max_length=64)
    payload = models.JSONField('请求内容', default=dict, blank=True)
    result = models.CharField('结果', max_length=16, default='success')
    error_message = models.TextField('错误信息', blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='操作人', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    class Meta:
        verbose_name = 'DNS 变更日志'
        verbose_name_plural = 'DNS 变更日志'
        ordering = ['-created_at']


class DNSQueryLog(models.Model):
    RESULT_CHOICES = [
        ('success', '成功'),
        ('failed', '失败'),
        ('unknown', '未知'),
    ]

    query_time = models.DateTimeField('解析时间')
    client_ip = models.GenericIPAddressField('客户端 IP', null=True, blank=True)
    query_name = models.CharField('查询域名', max_length=255)
    query_type = models.CharField('记录类型', max_length=16, blank=True)
    response_code = models.CharField('响应码', max_length=32, blank=True)
    answer = models.TextField('解析结果', blank=True)
    server_ip = models.GenericIPAddressField('DNS 服务 IP', null=True, blank=True)
    protocol = models.CharField('协议', max_length=16, blank=True)
    latency_ms = models.IntegerField('响应耗时', null=True, blank=True)
    result = models.CharField('结果', max_length=16, choices=RESULT_CHOICES, default='unknown')
    raw_message = models.TextField('原始日志', blank=True)
    created_at = models.DateTimeField('入库时间', auto_now_add=True)

    class Meta:
        verbose_name = 'DNS 解析记录'
        verbose_name_plural = 'DNS 解析记录'
        ordering = ['-query_time']
        indexes = [
            models.Index(fields=['-query_time']),
            models.Index(fields=['client_ip']),
            models.Index(fields=['query_name']),
            models.Index(fields=['query_type']),
            models.Index(fields=['response_code']),
        ]

    def __str__(self):
        return f'{self.client_ip or "-"} {self.query_name} {self.query_type}'
