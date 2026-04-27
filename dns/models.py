"""
DNS管理模块 - 数据模型
定义DNS服务器、全局配置、ACL、View、Zone、资源记录、转发规则等核心数据结构
支持BIND9配置的完整生命周期管理：草稿->待发布->校验->备份->发布->回滚
"""

import re
from django.db import models
from django.conf import settings


# ============================================================
# 1. DNS服务器实例
# ============================================================
class DnsServer(models.Model):
    """DNS服务器实例 - 管理本地或远程BIND9服务"""

    hostname = models.CharField('主机名', max_length=200)
    ip_address = models.GenericIPAddressField('管理IP', blank=True, null=True)
    bind_version = models.CharField('BIND版本', max_length=50, blank=True)
    named_conf_path = models.CharField('配置文件路径', max_length=500, default='/etc/named.conf')
    zone_dir = models.CharField('Zone文件目录', max_length=500, default='/var/named')
    log_file = models.CharField('日志文件路径', max_length=500, default='/var/log/named.log')
    is_local = models.BooleanField('本地服务器', default=True)
    enabled = models.BooleanField('启用监控', default=True)
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='创建人'
    )

    class Meta:
        verbose_name = 'DNS服务器'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.hostname} ({self.ip_address or '本地'})"

    @classmethod
    def get_local_server(cls):
        """获取本地默认DNS服务器"""
        server, _ = cls.objects.get_or_create(
            is_local=True,
            defaults={
                'hostname': 'localhost',
                'ip_address': '127.0.0.1',
                'named_conf_path': '/etc/named.conf',
                'zone_dir': '/var/named',
            }
        )
        return server


# ============================================================
# 2. 全局配置 (options {})
# ============================================================
class DnsGlobalOption(models.Model):
    """BIND9全局options配置 - 对应named.conf中的options{}块"""

    server = models.OneToOneField(DnsServer, on_delete=models.CASCADE,
                                  related_name='global_option', verbose_name='所属服务器')

    # 基础选项
    directory = models.CharField('工作目录', max_length=500, default='/var/named')
    pid_file = models.CharField('PID文件', max_length=500, blank=True)
    dump_file = models.CharField('缓存转储文件', max_length=500, blank=True)
    statistics_file = models.CharField('统计文件', max_length=500, blank=True)

    # 监听地址
    listen_on_v4 = models.TextField('IPv4监听地址', blank=True, help_text='每行一个IP，如 any 或 127.0.0.1')
    listen_on_v6 = models.CharField('IPv6监听方式', max_length=100, default='::1',
                                    help_text='any / ::1 / none')

    # 查询控制
    allow_query = models.TextField('允许查询来源', blank=True, help_text='每行一个: IP/CIDR/ACL名/any')
    allow_recursion = models.TextField('允许递归来源', blank=True)
    recursion = models.BooleanField('启用递归', default=False)

    # 安全选项
    dnssec_validation = models.CharField('DNSSEC验证', max_length=20, choices=(
        ('auto', '自动'), ('yes', '是'), ('no', '否')
    ), default='auto')
    auth_nxdomain = models.BooleanField('权威NXDOMAIN', default=False)
    empty_zones_enable = models.BooleanField('空区域启用', default=True)

    # 转发设置
    forward_policy = models.CharField('转发策略', max_length=10, choices=(
        ('first', '优先转发'), ('only', '仅转发'), ('', '不转发')
    ), default='', blank=True)
    forwarders = models.TextField('上游转发DNS', blank=True, help_text='每行一个IP地址')

    # 日志
    querylog_enable = models.BooleanField('查询日志', default=False)

    # 性能
    max_cache_size = models.CharField('最大缓存大小', max_length=50, blank=True)

    # 隐藏版本信息
    version_hide = models.BooleanField('隐藏版本信息', default=True)

    # 高级原始配置片段（无法用字段表达的直接写入）
    raw_config = models.TextField('高级原始配置', blank=True,
                                 help_text='原始named.conf options块内容，将追加在生成配置之后')

    # 状态标记
    is_draft = models.BooleanField('草稿状态', default=False,
                                   help_text='True表示尚未发布到正式配置')
    draft_updated_at = models.DateTimeField('草稿更新时间', null=True, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='最后修改人'
    )

    class Meta:
        verbose_name = '全局配置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"全局配置 - {self.server.hostname}"


# ============================================================
# 3-4. ACL 定义与条目
# ============================================================
class DnsAcl(models.Model):
    """BIND9 ACL定义 - 命名地址匹配列表"""

    name = models.CharField('ACL名称', max_length=100, unique=True)
    description = models.TextField('描述', blank=True)
    built_in = models.BooleanField('内置ACL', default=False,
                                   help_text='内置ACL不可删除(如any/none/localhost/localnets)')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'ACL'
        verbose_name_plural = verbose_name
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def item_count(self):
        return self.items.count()

    def can_delete(self):
        """检查是否可删除（无引用且非内置）"""
        if self.built_in:
            return False
        if self.used_in_view_clients.exists() or self.used_in_view_dests.exists():
            return False
        if DnsZone.objects.filter(allow_transfer_acl=self).exists():
            return False
        if DnsZone.objects.filter(allow_update_acl=self).exists():
            return False
        if DnsGlobalOption.objects.filter(id__isnull=False):  # 引用检查扩展点
            pass
        return True


class DnsAclItem(models.Model):
    """ACL条目 - 单个匹配元素"""

    ITEM_TYPE_CHOICES = (
        ('ip', 'IPv4地址'),
        ('ipv6', 'IPv6地址'),
        ('cidr', 'CIDR网段'),
        ('key', 'TSIG密钥'),
        ('acl_ref', '引用其他ACL'),
        ('any', '任意(any)'),
        ('none', '拒绝(none)'),
        ('localhost', '本机'),
        ('localnets', '本地网络'),
    )

    acl = models.ForeignKey(DnsAcl, on_delete=models.CASCADE,
                            related_name='items', verbose_name='所属ACL')
    item_type = models.CharField('条目类型', max_length=20, choices=ITEM_TYPE_CHOICES)
    value = models.CharField('值', max_length=500, blank=True,
                             help_text='IP/网段/密钥名称等，any/none类型无需填值')
    order_index = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = 'ACL条目'
        verbose_name_plural = verbose_name
        ordering = ['acl', 'order_index']

    def __str__(self):
        label = dict(self.ITEM_TYPE_CHOICES).get(self.item_type, self.item_type)
        return f"{label}: {self.value or '-'}"

    def render(self):
        """渲染为named.conf中的ACL条目文本"""
        type_map = {
            'ip': '{value}',
            'ipv6': '{value}',
            'cidr': '{value}',
            'key': 'key {value}',
            'acl_ref': '{value}',
            'any': 'any',
            'none': 'none',
            'localhost': 'localhost',
            'localnets': 'localnets',
        }
        template = type_map.get(self.item_type, '{value}')
        if self.item_type in ('any', 'none', 'localhost', 'localnets'):
            return template
        return template.format(value=self.value)


# ============================================================
# 5. View 视图
# ============================================================
class DnsView(models.Model):
    """BIND9 View - 根据客户端来源提供不同解析视图"""

    name = models.CharField('View名称', max_length=100, unique=True)
    match_clients = models.ManyToManyField(DnsAcl, blank=True,
                                           related_name='used_in_view_clients',
                                           verbose_name='匹配客户端(ACL)')
    match_destinations = models.ManyToManyField(DnsAcl, blank=True,
                                                related_name='used_in_view_dests',
                                                verbose_name='匹配目标(ACL)')
    recursion = models.BooleanField('递归设置', null=True, blank=True, default=None,
                                        help_text='留空继承全局配置')
    allow_query_acl = models.ForeignKey(DnsAcl, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='view_query', verbose_name='查询权限ACL')
    allow_recursion_acl = models.ForeignKey(DnsAcl, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name='view_recursion', verbose_name='递归权限ACL')
    description = models.TextField('描述', blank=True)
    order_index = models.IntegerField('排序', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'View视图'
        verbose_name_plural = verbose_name
        ordering = ['order_index', 'name']

    def __str__(self):
        return self.name

    @property
    def zone_count(self):
        return self.zones.count()


# ============================================================
# 6. Zone 区域 (核心模型)
# ============================================================
class DnsZone(models.Model):
    """DNS区域 - 正向/反向/主/从/转发区"""

    ZONE_TYPE_CHOICES = (
        ('master', '主区域(Master)'),
        ('slave', '从区域(Slave)'),
        ('forward', '转发区域(Forward)'),
        ('stub', '存根区域(Stub)'),
    )
    DIRECTION_CHOICES = (
        ('forward', '正向区域'),
        ('reverse', '反向区域'),
    )

    name = models.CharField('区域名称', max_length=255)
    zone_type = models.CharField('区域类型', max_length=20, choices=ZONE_TYPE_CHOICES, default='master')
    direction_type = models.CharField('方向', max_length=20, choices=DIRECTION_CHOICES, default='forward')
    view = models.ForeignKey(DnsView, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='zones', verbose_name='所属View')

    # 文件与TTL
    file_name = models.CharField('区域文件名', max_length=255, blank=True,
                                help_text='留空则自动按区域名生成')
    default_ttl = models.IntegerField('默认TTL(秒)', default=3600)

    # SOA 参数
    primary_ns = models.CharField('主DNS服务器(SOA)', max_length=255, blank=True)
    admin_mail = models.CharField('管理员邮箱(RNAME)', max_length=255, blank=True)
    serial_no = models.IntegerField('序列号(Serial)', default=2026042401)
    refresh = models.IntegerField('刷新间隔(秒)', default=3600,
                                  help_text='从服务器多久检查一次SOA Serial变化')
    retry = models.IntegerField('重试间隔(秒)', default=600,
                                 help_text='刷新失败后多久重试')
    expire = models.IntegerField('过期时间(秒)', default=86400,
                                 help_text='从服务器在多长时间内仍可响应查询')
    minimum = models.PositiveIntegerField('最小TTL(秒)', default=3600)

    # 主从相关 (slave区用)
    master_ips = models.TextField('主服务器IP', blank=True,
                                   help_text='Slave区填写Master服务器IP，逗号分隔')
    slave_ips = models.TextField('允许传输的Slave IP', blank=True,
                                 help_text='Master区填写允许AXFR的Slave IP列表')

    # 转发相关 (forward/stub区用)
    forwarders = models.TextField('转发目标', blank=True,
                                   help_text='Forward区填写转发目标IP，逗号分隔')
    forward_policy = models.CharField('转发策略', max_length=10, blank=True, choices=(
        ('first', '优先转发'), ('only', '仅转发')
    ))

    # 权限控制 ACL
    allow_transfer_acl = models.ForeignKey(DnsAcl, on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='zone_transfer', verbose_name='允许Zone传输(ACL)')
    allow_update_acl = models.ForeignKey(DnsAcl, on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='zone_update', verbose_name='允许动态更新(ACL)')

    dynamic_update = models.BooleanField('动态更新', default=False)
    enabled = models.BooleanField('启用', default=True)
    description = models.TextField('描述', blank=True)

    # 审计字段
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='创建人'
    )

    class Meta:
        verbose_name = '区域(Zone)'
        verbose_name_plural = verbose_name
        ordering = ['direction_type', 'name']

    def __str__(self):
        direction = self.get_direction_type_display()
        ztype = self.get_zone_type_display()
        return f"[{ztype}/{direction}] {self.name}"

    @property
    def record_count(self):
        return self.records.filter(enabled=True).count()

    def generate_filename(self):
        """根据区域名称生成默认文件名"""
        if self.file_name:
            return self.file_name
        safe_name = self.name.replace('.', '_').replace('-', '_').replace('/', '_')
        return f"zone.{safe_name}"

    def bump_serial(self):
        """递增SOA序列号"""
        today_str = str(self.serial_no)[:8]
        from datetime import date
        today_date = date.today().strftime('%Y%m%d')
        if today_str == today_date:
            # 同日递增后2位
            seq = int(str(self.serial_no)[8:]) + 1
            self.serial_no = int(f"{today_date}{seq:02d}")
        else:
            # 新日期重置为01
            self.serial_no = int(f"{today_date}01")
        self.save(update_fields=['serial_no', 'updated_at'])

    def get_soa_record(self):
        """获取该区域的SOA记录（如果有）"""
        try:
            return self.records.get(record_type='SOA', enabled=True)
        except DnsRecord.DoesNotExist:
            return None

    def clean(self):
        """模型级校验"""
        super().clean()
        if self.zone_type == 'slave' and not self.master_ips:
            from django.core.exceptions import ValidationError
            raise ValidationError({'master_ips': '从区域(Slave)必须指定主服务器IP'})
        if self.zone_type in ('forward', 'stub') and not self.forwarders:
            from django.core.exceptions import ValidationError
            raise ValidationError({'forwarders': '转发区域必须指定转发目标'})


# ============================================================
# 7. 资源记录
# ============================================================
class DnsRecord(models.Model):
    """DNS资源记录 - SOA/NS/A/AAAA/CNAME/MX/PTR/TXT/SRV"""

    RECORD_TYPE_CHOICES = (
        ('SOA', 'SOA'),
        ('NS', 'NS'),
        ('A', 'A (IPv4)'),
        ('AAAA', 'AAAA (IPv6)'),
        ('CNAME', 'CNAME (别名)'),
        ('MX', 'MX (邮件)'),
        ('PTR', 'PTR (指针)'),
        ('TXT', 'TXT (文本)'),
        ('SRV', 'SRV (服务)'),
    )

    zone = models.ForeignKey(DnsZone, on_delete=models.CASCADE,
                               related_name='records', verbose_name='所属区域')
    record_type = models.CharField('记录类型', max_length=10, choices=RECORD_TYPE_CHOICES)
    name = models.CharField('记录名称', max_length=255, default='@',
                            help_text='相对名称或 @ 表示区域本身')
    ttl = models.IntegerField('TTL(秒)', null=True, blank=True,
                               help_text='留空使用区域默认TTL')
    value = models.TextField('记录值', help_text='A=IPv4, CNAME=FQDN, MX="优先级 目标" 等')
    priority = models.IntegerField('优先级', null=True, blank=True,
                                   help_text='MX/SRV记录的优先级或权重')
    weight = models.IntegerField('权重', null=True, blank=True, help_text='SRV权重')
    port = models.IntegerField('端口', null=True, blank=True, help_text='SRV端口')
    enabled = models.BooleanField('启用', default=True)

    # 审计字段
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='创建人'
    )

    class Meta:
        verbose_name = '资源记录'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['zone', 'record_type', 'name']),
            models.Index(fields=['record_type']),
        ]
        ordering = ['record_type', 'name']

    def __str__(self):
        return f"{self.record_type} {self.name} -> {self.value[:50]}"

    def clean(self):
        """业务规则校验"""
        super().clean()
        from django.core.exceptions import ValidationError
        errors = {}

        # 安全获取 zone（可能是实例、PK值、或未设置）
        _zone = self.zone
        if _zone is None or not isinstance(_zone, DnsZone):
            # zone 未设或非实例时跳过关联校验
            if errors:
                raise ValidationError(errors)
            return

        # CNAME 不能与同名其他记录并存（RFC规范）
        if self.record_type == 'CNAME':
            existing = DnsRecord.objects.filter(
                zone=_zone, name=self.name, enabled=True
            ).exclude(pk=self.pk or 0).exclude(record_type='CNAME')
            if existing.exists():
                errors['name'] = f'该名称已存在 {existing.first().record_type} 类型记录，不能同时存在CNAME'

        # 如果已有同名CNAME，不能再添加其他记录
        if self.record_type != 'CNAME':
            cname_exists = DnsRecord.objects.filter(
                zone=_zone, record_type='CNAME', name=self.name, enabled=True
            ).exclude(pk=self.pk or 0).exists()
            if cname_exists:
                errors['name'] = '该名称已存在CNAME记录，不能添加其他类型记录'

        # A 记录值必须是合法 IPv4
        if self.record_type == 'A' and self.value:
            if not re.match(r'^(\d{1,3}\.){3}\d{1,3}$', self.value):
                errors['value'] = '无效的IPv4地址'

        # AAAA 必须合法 IPv6
        if self.record_type == 'AAAA' and self.value:
            import ipaddress
            try:
                ipaddress.IPv6Address(self.value)
            except ValueError:
                errors['value'] = '无效的IPv6地址'

        # MX 必须有优先级
        if self.record_type == 'MX' and not self.priority:
            errors['priority'] = 'MX记录必须指定优先级'

        # PTR/CNAME 值必须是FQDN（以.结尾或含点）
        if self.record_type in ('PTR', 'CNAME') and self.value:
            val = self.value.strip()
            if not val.endswith('.') and '.' not in val:
                errors['value'] = f'{self.record_type}记录值必须为FQDN（如 ns.example.com.）'

        # NS 至少保留一条（删除时由视图层处理）
        if errors:
            raise ValidationError(errors)


# ============================================================
# 8. 转发规则
# ============================================================
class DnsForwardRule(models.Model):
    """DNS转发规则 - 全局转发和条件转发"""

    RULE_TYPE_CHOICES = (
        ('global', '全局转发'),
        ('conditional', '条件转发'),
    )
    POLICY_CHOICES = (
        ('only', '仅转发(only)'),
        ('first', '优先转发(first)'),
    )

    rule_type = models.CharField('规则类型', max_length=20, choices=RULE_TYPE_CHOICES)
    zone = models.ForeignKey(DnsZone, on_delete=models.CASCADE, null=True, blank=True,
                              related_name='forward_rules', verbose_name='关联区域(条件转发)')
    forwarders = models.TextField('转发目标IP', help_text='逗号或换行分隔的IP地址列表')
    policy = models.CharField('转发策略', max_length=10, choices=POLICY_CHOICES, default='first')
    description = models.TextField('描述', blank=True)
    enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '转发规则'
        verbose_name_plural = verbose_name

    def __str__(self):
        target = self.zone.name if self.zone else '全局'
        return f"[{self.get_rule_type_display()}] {target}"


# ============================================================
# 9. 主从同步状态
# ============================================================
class DnsSyncStatus(models.Model):
    """Zone主从同步状态跟踪"""

    zone = models.OneToOneField(DnsZone, on_delete=models.CASCADE,
                                 related_name='sync_status', verbose_name='所属区域')
    local_serial = models.IntegerField('本地Serial', default=0)
    remote_serial = models.IntegerField('远端Serial', null=True, blank=True)
    last_sync_time = models.DateTimeField('上次同步时间', null=True, blank=True)
    last_sync_result = models.CharField('上次同步结果', max_length=50, blank=True)
    last_sync_message = models.TextField('同步详情消息', blank=True)
    also_notify = models.TextField('主动通知列表', blank=True, help_text='变更时通知的目标IP')

    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主从同步状态'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"同步状态: {self.zone.name} (L={self.local_serial}, R={self.remote_serial})"

    @property
    def in_sync(self):
        if self.remote_serial is None:
            return None
        return self.local_serial == self.remote_serial


# ============================================================
# 10-11. 发布版本与对象
# ============================================================
class DnsPublishVersion(models.Model):
    """发布版本 - 一次完整发布的快照"""

    VERSION_STATUS_CHOICES = (
        ('pending', '待发布'),
        ('publishing', '发布中'),
        ('success', '发布成功'),
        ('failed', '发布失败'),
        ('rolled_back', '已回滚'),
    )

    version_number = models.CharField('版本号', max_length=50)
    status = models.CharField('状态', max_length=20, choices=VERSION_STATUS_CHOICES, default='pending')
    publisher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                  null=True, blank=True, verbose_name='发布人')
    publish_time = models.DateTimeField('发布时间', null=True, blank=True)
    notes = models.TextField('备注', blank=True)

    # 校验结果摘要
    checkconf_passed = models.BooleanField('checkconf通过', null=True)
    checkzone_results = models.TextField('checkzone结果摘要', blank=True)

    # 统计
    object_count = models.IntegerField('变更对象数', default=0)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '发布版本'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"v{self.version_number} ({self.get_status_display()})"


class DnsPublishObject(models.Model):
    """发布对象 - 单个版本中包含的具体变更"""

    ACTION_CHOICES = (('create', '新增'), ('update', '修改'), ('delete', '删除'))
    OBJECT_TYPE_CHOICES = (
        ('global_option', '全局配置'),
        ('acl', 'ACL'),
        ('acl_item', 'ACL条目'),
        ('view', 'View'),
        ('zone', '区域'),
        ('record', '资源记录'),
        ('forward', '转发规则'),
    )

    version = models.ForeignKey(DnsPublishVersion, on_delete=models.CASCADE,
                                 related_name='publish_objects', verbose_name='所属版本')
    object_type = models.CharField('对象类型', max_length=30, choices=OBJECT_TYPE_CHOICES)
    object_id = models.IntegerField('对象ID', null=True, blank=True)
    object_name = models.CharField('对象标识', max_length=255)  # 可读标识用于展示
    action = models.CharField('操作', max_length=20, choices=ACTION_CHOICES)
    diff_content = models.TextField('变更Diff', blank=True)
    check_result = models.CharField('校验结果', max_length=20, blank=True,
                                     help_text='pass/fail/error/skipped')
    publish_status = models.CharField('发布结果', max_length=20, blank=True)

    class Meta:
        verbose_name = '发布对象'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"[{self.action}] {self.object_type}: {self.object_name}"


# ============================================================
# 12. 备份
# ============================================================
class DnsBackup(models.Model):
    """配置备份 - 发布前或手动触发的配置快照"""

    BACKUP_TYPE_CHOICES = (
        ('pre_publish', '发布前自动备份'),
        ('manual', '手动备份'),
        ('scheduled', '定时备份'),
    )

    version = models.ForeignKey(DnsPublishVersion, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='backups',
                                 verbose_name='关联发布版本')
    backup_type = models.CharField('备份类型', max_length=20, choices=BACKUP_TYPE_CHOICES)
    config_content = models.TextField('named.conf内容')  # 配置文件快照
    file_size = models.IntegerField('文件大小(字节)', default=0)
    storage_path = models.CharField('存储路径', max_length=500, blank=True)
    backup_time = models.DateTimeField('备份时间', auto_now_add=True)
    backup_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, verbose_name='操作人')
    notes = models.TextField('备注', blank=True)

    class Meta:
        verbose_name = '配置备份'
        verbose_name_plural = verbose_name
        ordering = ['-backup_time']

    def __str__(self):
        return f"备份 v{self.version.version_number if self.version else '?'} @ {self.backup_time}"


# ============================================================
# 13. DNS专用审计日志
# ============================================================
class DnsAuditLog(models.Model):
    """DNS模块审计日志 - 比OperationLog更详细的操作记录"""

    ACTION_CHOICES = (
        ('create_zone', '新建区域'),
        ('update_zone', '编辑区域'),
        ('delete_zone', '删除区域'),
        ('enable_zone', '启用区域'),
        ('disable_zone', '禁用区域'),
        ('create_record', '新建记录'),
        ('update_record', '编辑记录'),
        ('delete_record', '删除记录'),
        ('batch_import_records', '批量导入记录'),
        ('batch_export_records', '批量导出记录'),
        ('create_acl', '新建ACL'),
        ('update_acl', '编辑ACL'),
        ('delete_acl', '删除ACL'),
        ('create_view', '新建View'),
        ('update_view', '编辑View'),
        ('delete_view', '删除View'),
        ('update_global_option', '修改全局配置'),
        ('publish', '执行发布'),
        ('rollback', '执行回滚'),
        ('service_start', '启动服务'),
        ('service_stop', '停止服务'),
        ('service_restart', '重启服务'),
        ('service_reload', '重新加载'),
        ('service_reconfig', '重读配置'),
        ('service_flush_cache', '清理缓存'),
        ('config_sync', '配置同步'),
        ('manual_backup', '手动备份'),
    )
    CATEGORY_CHOICES = (
        ('zone', '区域管理'),
        ('record', '记录管理'),
        ('acl', 'ACL管理'),
        ('view', 'View管理'),
        ('global', '全局配置'),
        ('service', '服务管理'),
        ('publish', '发布管理'),
        ('backup', '备份管理'),
        ('sync', '同步管理'),
        ('audit', '审计操作'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, verbose_name='操作用户')
    action = models.CharField('操作', max_length=50, choices=ACTION_CHOICES)
    category = models.CharField('类别', max_length=30, choices=CATEGORY_CHOICES)
    object_name = models.CharField('操作对象', max_length=255, blank=True)
    detail = models.TextField('操作详情', blank=True)
    old_value = models.TextField('变更前', blank=True)
    new_value = models.TextField('变更后', blank=True)
    result = models.CharField('执行结果', max_length=20, default='success',
                              choices=(('success', '成功'), ('failed', '失败'), ('pending', '进行中')))
    client_ip = models.GenericIPAddressField('客户端IP', null=True, blank=True)
    operation_time = models.DateTimeField('操作时间', auto_now_add=True)

    class Meta:
        verbose_name = 'DNS审计日志'
        verbose_name_plural = verbose_name
        ordering = ['-operation_time']
        indexes = [
            models.Index(fields=['category', 'action']),
            models.Index(fields=['object_name']),
            models.Index(fields=['operation_time']),
        ]

    def __str__(self):
        return f"{self.user} {self.get_action_display()} @{self.operation_time}"
