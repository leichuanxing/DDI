"""
BIND9 配置渲染引擎
从数据库ORM模型生成完整的named.conf文本和各Zone文件文本

渲染规则:
1. options{}块从DnsGlobalOption模型读取
2. acl{}块从DnsAcl/DnsAclItem模型读取
3. view/zone{}块从DnsView/DnsZone模型读取
4. include语句按层级组织
5. 注释自动添加来源标记便于调试

P5: 完整实现全部渲染方法，支持完整named.conf生成和zone文件生成
"""

from datetime import datetime, date


class ConfigRenderer:
    """BIND9配置文件渲染器 - 从DB ORM → BIND9配置文本"""

    HEADER_COMMENT = (
        "// ============================================================\n"
        "// BIND9 配置文件 - 由DDI管理系统自动生成\n"
        "// 生成时间: {timestamp}\n"
        "// 请勿手动编辑此文件！修改请通过Web界面进行\n"
        "// ============================================================\n\n"
    )

    def __init__(self, server=None):
        self.server = server
        self.output_lines = []

    def render_full_config(self) -> str:
        """渲染完整named.conf内容

        生成顺序 (符合BIND9语法要求):
        1. 头部注释
        2. ACL定义（必须在options/view引用之前）
        3. 全局options{}块
        4. logging{}块（如有）
        5. 不属于任何View的默认zones
        6. View块（含各自zone子块）
        7. 尾部注释

        Returns:
            str: 完整的named.conf文本
        """
        lines = []
        lines.append(self.HEADER_COMMENT.format(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))

        # 1) ACL定义（必须在options和view之前声明）
        acl_text = self.render_acl_block()
        if acl_text:
            lines.append(acl_text)

        # 2) 全局options
        lines.append(self.render_options_block())

        # 3) logging（预留扩展点，当前返回空字符串）
        logging_text = self.render_logging_block()
        if logging_text:
            lines.append(logging_text)

        # 4) 无View时的默认zones（root hints / localhost zones等）
        default_zones = self.render_default_zones()
        if default_zones:
            lines.append(default_zones)

        # 5) 自定义View块及其zones
        view_blocks = self.render_view_blocks()
        if view_blocks:
            lines.append(view_blocks)

        # 6) 文件结尾注释
        lines.append("\n// === End of auto-generated configuration ===\n")

        return '\n'.join(lines)

    def render_options_block(self) -> str:
        """渲染options{}块 - 从DnsGlobalOption模型读取全部字段

        渲染字段清单:
        - directory, pid-file, dump-file, statistics-file
        - listen-on port 53, listen-on-v6 port 53
        - allow-query{}, allow-recursion{}
        - recursion, dnssec-validation, auth-nxdomain, empty-zones-enable
        - version "none" (隐藏版本)
        - forward policy + forwarders{}
        - querylog, max-cache-size
        - raw_config (用户自定义高级片段)

        Returns:
            str: options{}块的完整文本
        """
        from ..models import DnsServer, DnsGlobalOption

        lines = ["options {"]

        try:
            server = self.server or DnsServer.get_local_server()
            opt = DnsGlobalOption.objects.filter(server=server).first()

            if not opt:
                lines.append("\tdirectory \"/var/named\";")
                lines.append("\t// 使用默认配置（未找到全局配置记录）")
                lines.append("};")
                return '\n'.join(lines) + '\n'

            # --- 基础目录 ---
            lines.append(f'\tdirectory "{opt.directory or "/var/named"}";')

            # 文件路径
            for field_name in ['pid_file', 'dump_file', 'statistics_file']:
                value = getattr(opt, field_name, None)
                if value:
                    conf_key = field_name.replace('_', '-')
                    lines.append(f"\t{conf_key} \"{value}\";")

            # --- 监听地址 ---
            if opt.listen_on_v4 and opt.listen_on_v4.strip():
                ips = [ip.strip() for ip in opt.listen_on_v4.splitlines() if ip.strip()]
                if len(ips) == 1:
                    lines.append(f"\tlisten-on port 53 {{ {ips[0]}; }};")
                elif len(ips) > 1:
                    lines.append(f"\tlisten-on port 53 {{ {'; '.join(ips)}; }};")
                else:
                    lines.append('\tlisten-on port 53 { any; };')
            else:
                lines.append('\tlisten-on port 53 { any; };')

            # IPv6监听
            listen_v6 = opt.listen_on_v6 or 'any'
            if not listen_v6 or listen_v6 == 'any':
                listen_v6 = 'any'  # 默认值
            lines.append(f"\tlisten-on-v6 port 53 {{ {listen_v6}; }};")

            # --- 查询控制 ---
            if opt.allow_query and opt.allow_query.strip():
                aq_items = [aq.strip() for aq in opt.allow_query.splitlines() if aq.strip()]
                if aq_items:
                    lines.append(f"\tallow-query {{ {'; '.join(aq_items)} }};")

            if opt.allow_recursion and opt.allow_recursion.strip():
                ar_items = [ar.strip() for ar in opt.allow_recursion.splitlines() if ar.strip()]
                if ar_items:
                    lines.append(f"\tallow-recursion {{ {'; '.join(ar_items)} }};")

            if opt.recursion:
                lines.append('\trecursion yes;')

            # --- 安全选项 ---
            if opt.dnssec_validation and opt.dnssec_validation != 'auto':
                lines.append(f'\tdnssec-validation {opt.dnssec_validation};')
            else:
                lines.append('\tdnssec-validation auto;')  # 明确输出默认值

            if opt.auth_nxdomain:
                lines.append('\tauth-nxdomain yes;')
            if opt.empty_zones_enable:
                lines.append('\tempty-zones-enable yes;')

            # 隐藏BIND版本号（安全最佳实践）
            if opt.version_hide:
                lines.append('\tversion "none";')

            # --- 转发设置 ---
            if opt.forward_policy:
                lines.append(f"\tforward {opt.forward_policy};")
                if opt.forwarders and opt.forwarders.strip():
                    fwd_ips = [f.strip() for f in opt.forwarders.splitlines() if f.strip()]
                    if fwd_ips:
                        lines.append(f"\tforwarders {{ {'; '.join(fwd_ips)}; }};")

            # --- 日志 ---
            if opt.querylog_enable:
                lines.append('\tquerylog yes;')

            # --- 性能调优 ---
            if opt.max_cache_size:
                lines.append(f'\tmax-cache-size {opt.max_cache_size};')

            # --- 用户自定义高级配置（原样追加）---
            if opt.raw_config and opt.raw_config.strip():
                lines.append('\t// === 用户自定义高级配置 (raw_config) ===')
                for raw_line in opt.raw_config.split('\n'):
                    raw_line = raw_line.strip()
                    if raw_line and not raw_line.startswith('//'):
                        lines.append(f'\t{raw_line}')

        except Exception as e:
            # 异常时使用安全的最低配置
            import logging
            logger = logging.getLogger('dns.config_renderer')
            logger.error(f'render_options_block error: {e}')
            lines.append("\tdirectory \"/var/named\";")
            lines.append("\t// 配置渲染异常，使用默认设置")

        lines.append("};")
        lines.append("")
        return '\n'.join(lines)

    def render_acl_block(self) -> str:
        """渲染所有ACL定义块

        格式:
            acl "ACL名称" {
                item1;
                item2;
                key "tsig-key-name";
            };

        Returns:
            str: 所有acl{}块拼接后的文本（无ACL时返回空字符串）
        """
        from ..models import DnsAcl
        acls = DnsAcl.objects.all().prefetch_related('items').order_by('name')
        if not acls.exists():
            return ''

        lines = ["// ===== ACL 定义 (共{}个) =====".format(acls.count())]
        for acl in acls:
            items_list = list(acl.items.all().order_by('order_index'))
            lines.append(f'acl "{acl.name}" {{')
            if items_list:
                for item in items_list:
                    lines.append(f'\t{item.render()};')
            else:
                lines.append('\t// (空ACL)')
            lines.append("};")
            lines.append("")
        return '\n'.join(lines)

    def render_logging_block(self) -> str:
        """渲染logging{}块（预留扩展点）

        未来可支持从DB配置logging channel/category。
        当前返回空字符串。

        Returns:
            str: 空字符串（无logging配置）
        """
        # 预留: 未来可从DnsLoggingConfig等模型读取并渲染
        return ""

    def render_default_zones(self) -> str:
        """渲染不属于任何View的Zone块

        这些zone直接出现在全局作用域中（不在view内）。
        包括: root hints zone、localhost zones、用户创建的无view zone等。

        Returns:
            str: 默认zone块文本（无默认zone时返回空字符串）
        """
        from ..models import DnsZone
        zones = DnsZone.objects.filter(view__isnull=True, enabled=True).order_by(
            'direction_type', 'name'
        )
        if not zones.exists():
            return ""

        lines = [
            "// ===== 默认视图区域 (不属于任何View) =====",
            f"// 共 {zones.count()} 个区域",
        ]
        for zone in zones:
            lines.append('')
            lines.append(self._render_single_zone(zone))
        return '\n'.join(lines) + '\n'

    def render_view_blocks(self) -> str:
        """渲染所有View块及其内部Zone

        每个view格式:
            view "view-name" {
                match-clients { ... };
                match-destinations { ... };
                recursion yes/no;
                // zone blocks...
            };

        Returns:
            str: 所有view块拼接后的文本（无view时返回空字符串）
        """
        from ..models import DnsView
        views = DnsView.objects.all().prefetch_related(
            'match_clients', 'match_destinations', 'zones'
        ).order_by('order_index', 'name')
        if not views.exists():
            return ''

        lines = [f"// ===== 视图定义 (共{views.count()}个) ====="]

        for view in views:
            lines.append(f'view "{view.name}" {{')

            # match-clients
            if view.match_clients.exists():
                clients = '; '.join(a.name for a in view.match_clients.all())
                lines.append(f'\tmatch-clients {{ {clients}; }};')

            # match-destinations
            if view.match_destinations.exists():
                dests = '; '.join(a.name for a in view.match_destinations.all())
                lines.append(f'\tmatch-destinations {{ {dests}; }};')

            # recursion (None=继承全局, True/False=显式指定)
            if view.recursion is not None:
                lines.append(f'\trecursion {"yes" if view.recursion else "no"};')

            # allow-query ACL (view级) — 直接引用ACL名(非TSIG key)
            if view.allow_query_acl:
                lines.append(f'\tallow-query {{ {view.allow_query_acl.name}; }};')

            # allow-recursion ACL (view级)
            if view.allow_recursion_acl:
                lines.append(f'\tallow-recursion {{ {view.allow_recursion_acl.name}; }};')

            # 该View下的Zones
            zones = view.zones.filter(enabled=True).order_by('direction_type', 'name')
            if zones.exists():
                lines.append(f'\t// 共 {zones.count()} 个区域')
                for zone in zones:
                    lines.append(self._render_single_zone(zone, indent='\t'))
            else:
                lines.append('\t// (该视图下暂无区域)')

            lines.append("};")
            lines.append("")

        return '\n'.join(lines)

    def _render_single_zone(self, zone, indent='') -> str:
        """渲染单个zone块

        Args:
            zone: DnsZone ORM对象
            indent: 缩进前缀（用于嵌套在view内，如 '\\t'）

        Returns:
            str: zone{}块文本

        示例输出:
            zone "example.com" {
                type master;
                file "zone.example.com";
                allow-transfer { key "xfer-acl"; };
            };
        """
        ztype_map = {
            'master': 'type master',
            'slave': 'type slave',
            'forward': 'type forward',
            'stub': 'type stub',
        }
        type_line = ztype_map.get(zone.zone_type, 'type master')

        filename = zone.file_name or zone.generate_filename()

        lines = [f'{indent}zone "{zone.name}" {{']
        lines.append(f'{indent}\t{type_line};')
        lines.append(f'{indent}\tfile "{filename}";')

        # Slave区: masters {}
        if zone.zone_type == 'slave' and zone.master_ips:
            masters = '; '.join(m.strip() for m in zone.master_ips.split(',') if m.strip())
            lines.append(f'{indent}\tmasters {{ {masters} }};')

        # Forward/Stub区: forwarders {} + forward policy
        if zone.zone_type in ('forward', 'stub') and zone.forwarders:
            fwd = '; '.join(f.strip() for f in zone.forwarders.split(',') if f.strip())
            policy = zone.forward_policy or 'first'
            lines.append(f'{indent}\tforwarders {{ {fwd}; }};')
            lines.append(f'{indent}\tforward {policy};')

        # 权限控制: allow-transfer
        if zone.allow_transfer_acl:
            lines.append(f'{indent}\tallow-transfer {{ {zone.allow_transfer_acl.name}; }};')

        # allow-update
        if zone.allow_update_acl:
            lines.append(f'{indent}\tallow-update {{ {zone.allow_update_acl.name}; }};')

        # also-notify (从sync_status获取)
        try:
            sync_status = getattr(zone, 'sync_status', None)
            if sync_status and sync_status.also_notify:
                notify_ips = '; '.join(
                    ip.strip() for ip in sync_status.also_notify.split(',') if ip.strip()
                )
                lines.append(f'{indent}\talso-notify {{ {notify_ips} }};')
        except Exception:
            pass

        lines.append(f'{indent}}};')
        return '\n'.join(lines)

    def render_zone_file(self, zone) -> str:
        """渲染单个Zone的资源记录文件(SOA+NS+A等资源记录)

        生成标准BIND9 zone file格式:
        - $TTL 指令
        - SOA记录（多行格式，含Serial/Refresh/Retry/Expire/Minimum）
        - NS记录列表
        - A/AAAA/CNAME/MX/PTR/TXT/SRV 其他记录

        Args:
            zone: DnsZone ORM对象（需包含关联records）

        Returns:
            str: zone文件完整文本
        """
        from ..utils.helpers import normalize_fqdn, validate_soa_rname

        ttl = zone.default_ttl or 3600

        header = [
            f'$TTL {ttl}',
            f'; Zone file for {zone.name} - Auto-generated by DDI System at {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            '; ============================================',
            '',
        ]

        origin = zone.name.rstrip('.') + '.' if not zone.name.endswith('.') else zone.name

        # SOA记录
        soa = zone.get_soa_record()
        if soa:
            # 主NS服务器（优先使用SOA记录value中的NS，回退到zone.primary_ns）
            ns_value = ''
            if soa.value:
                parts = soa.value.split(None, 2)
                if len(parts) >= 1:
                    ns_value = parts[0].rstrip('.')
            primary_ns = ns_value or zone.primary_ns or ('ns.' + origin)

            # RNAME（管理员邮箱）
            rname_raw = zone.admin_mail or ''
            if soa.value:
                parts = soa.value.split(None, 2)
                if len(parts) >= 2:
                    rname_raw = parts[1]  # SOA第二段是RNAME
            rname = validate_soa_rname(rname_raw)

            serial = zone.serial_no or generate_serial_for_zone(zone)

            # 多行SOA格式 — 动态对齐：名称后跟Tab+IN，兼容长短区域名
            header.extend([
                f"{origin}\tIN\tSOA\t{primary_ns}\t{rname} (",
                f"\t\t\t{serial}\t\t\t; Serial ({datetime.now().strftime('%Y%m%d')})",
                f"\t\t\t{zone.refresh or 3600}\t\t; Refresh",
                f"\t\t\t{zone.retry or 600}\t\t\t; Retry",
                f"\t\t\t{zone.expire or 86400}\t\t; Expire",
                f"\t\t\t{zone.minimum or 3600}\t\t; Minimum TTL",
                ")",
                "",
            ])
        else:
            # 无SOA记录时添加警告
            header.extend([
                f"; WARNING: Zone '{zone.name}' has no SOA record!",
                "; Please add an SOA record via the web interface.",
                "",
            ])

        # NS记录
        ns_records = zone.records.filter(record_type='NS', enabled=True).order_by('name')
        if ns_records.exists():
            for r in ns_records:
                name = normalize_fqdn(r.name if r.name != '@' else '@', origin)
                target = r.value if r.value.endswith('.') else r.value + '.'
                header.append(f"{name}\tIN\tNS\t\t{target}")
            header.append('')
        else:
            # 至少保证有一条NS记录（用主NS作为默认）
            if zone.primary_ns:
                default_ns = zone.primary_ns if zone.primary_ns.endswith('.') else zone.primary_ns + '.'
                header.append(f"{origin}\tIN\tNS\t\t{default_ns}")
                header.append('; Default NS from zone settings (add NS records for production)')
                header.append('')

        # 其他类型记录（按类型分组排序）
        other_type_order = ['A', 'AAAA', 'CNAME', 'MX', 'PTR', 'TXT', 'SRV']

        for rtype in other_type_order:
            records = zone.records.filter(record_type=rtype, enabled=True).order_by('name')
            for r in records:
                name = normalize_fqdn(r.name if r.name != '@' else '@', origin)

                if r.record_type == 'MX':
                    prio = r.priority or 10
                    target = r.value if r.value.endswith('.') else r.value + '.'
                    header.append(f"{name}\tIN\tMX\t\t{prio}\t{target}")
                elif r.record_type == 'TXT':
                    # TXT值需要引号包裹（如果尚未包裹）
                    txt_val = r.value
                    if not (txt_val.startswith('"') and txt_val.endswith('"')):
                        txt_val = f'"{txt_val}"'
                    header.append(f"{name}\tIN\tTXT\t\t{txt_val}")
                elif r.record_type == 'SRV':
                    prio = r.priority or 0
                    weight = r.weight or 0
                    port_val = r.port or 0
                    target = r.value if r.value.endswith('.') else r.value + '.'
                    header.append(f"{name}\tIN\tSRV\t\t{prio}\t{weight}\t{port_val}\t{target}")
                elif r.record_type == 'PTR':
                    # PTR值必须为FQDN（以.结尾）
                    target = r.value if r.value.endswith('.') else r.value + '.'
                    header.append(f"{name}\tIN\tPTR\t\t{target}")
                elif r.record_type == 'CNAME':
                    # CNAME目标必须为FQDN（以.结尾）
                    target = r.value if r.value.endswith('.') else r.value + '.'
                    header.append(f"{name}\tIN\tCNAME\t\t{target}")
                elif r.ttl is not None:
                    # 有自定义TTL
                    header.append(f"{name}\t{r.ttl}\tIN\t{rtype}\t{r.value}")
                else:
                    header.append(f"{name}\tIN\t{rtype}\t\t{r.value}")

        header.append('; End of auto-generated zone file')
        return '\n'.join(header)


def generate_serial_for_zone(zone=None):
    """为Zone生成或获取当前有效Serial号码

    优先使用zone.serial_no（如果已存在），否则按日期生成新serial。
    如果zone.serial_no是今天日期开头的，则递增后两位；否则重新生成。

    Args:
        zone: DnsZone对象（可选）

    Returns:
        int: 有效serial号码
    """
    today_base = int(date.today().strftime('%Y%m%d')) * 100

    if zone and zone.serial_no:
        existing_base = zone.serial_no // 100 * 100
        if existing_base == today_base:
            # 同日: 递增
            new_seq = (zone.serial_no % 100) + 1
            if new_seq > 99:
                new_seq = 99
            return today_base + new_seq
        # 跨日: 使用今天日期
        return today_base + 1

    return today_base + 1


def render_bind_config(server=None) -> str:
    """便捷函数：渲染完整的named.conf配置

    Args:
        server: DnsServer对象（可选，不传则使用本地服务器）

    Returns:
        str: 完整的named.conf文本
    """
    renderer = ConfigRenderer(server)
    return renderer.render_full_config()


def render_zone_file(zone) -> str:
    """便捷函数：渲染单个Zone文件

    Args:
        zone: DnsZone对象

    Returns:
        str: Zone文件完整文本
    """
    renderer = ConfigRenderer()
    return renderer.render_zone_file(zone)
