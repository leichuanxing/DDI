"""
DNS辅助工具函数
提供域名/FQDN/SOASerial/IP格式校验等通用工具
"""

import re
import ipaddress
from datetime import date


def is_valid_domain(domain: str) -> bool:
    """校验域名格式合法性

    Args:
        domain: 域名字符串，如 example.com, www.test-site.org

    Returns:
        bool: 是否为合法域名
    """
    if not domain or len(domain) > 253:
        return False
    pattern = r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)*$'
    return bool(re.match(pattern, domain.lower(), re.I))


def is_valid_fqdn(fqdn: str) -> bool:
    """校验FQDN格式（必须以点结尾或包含至少一个点）

    Args:
        fqdn: FQDN字符串，如 ns1.example.com. 或 ns1.example.com
    """
    if not fqdn:
        return False
    if fqdn.endswith('.'):
        return is_valid_domain(fqdn[:-1])
    return '.' in fqdn and is_valid_domain(fqdn)


def normalize_fqdn(name: str, origin: str = '') -> str:
    """规范化域名：将相对名转为FQDN

    规则:
    - @ 或空 → 返回 origin + 尾部点
    - 已是FQDN（含尾部点）→ 保持不变
    - 含点但非FQDN → 追加origin并加尾部点
    - 纯相对名 → 追加origin并加尾部点

    Examples:
        normalize_fqdn('@', 'example.com.') → 'example.com.'
        normalize_fqdn('www', 'example.com.') → 'www.example.com.'
        normalize_fqdn('mail.google.com.', 'example.com.') → 'mail.google.com.'

    Args:
        name: 输入名称
        origin: 起源区域名（应已含尾部点）

    Returns:
        str: 规范化的FQDN（保证以 . 结尾）
    """
    if not name or name == '@' or name.strip() == '':
        return origin.rstrip('.') + '.' if origin else '@'

    name = name.strip().rstrip('.')
    if '.' in name and is_valid_fqdn(name + '.'):
        return name + '.'

    if origin:
        return f"{name}.{origin.rstrip('.')}."
    return name + '.'


def generate_serial(date_obj=None, seq=None) -> int:
    """生成标准SOA Serial号码

    格式: YYYYMMDDNN (日期 + 当日递增序号)

    Args:
        date_obj: 日期对象，默认今天
        seq: 序号(00-99)，默认01

    Returns:
        int: 标准SOA serial号码
    """
    d = date_obj or date.today()
    base = int(d.strftime('%Y%m%d'))
    s = max(0, min(99, seq or 1))
    return base * 100 + s


def increment_serial(current_serial: int) -> int:
    """递增Serial号码

    同日递增后两位，跨日则重置为新日期+01。
    如果后两位已达99，溢出归1（极端情况）。

    Args:
        current_serial: 当前serial号

    Returns:
        int: 新的serial号
    """
    today_base = int(date.today().strftime('%Y%m%d')) * 100
    serial_base = current_serial // 100 * 100

    if serial_base == today_base:
        # 同日递增
        new_seq = (current_serial % 100) + 1
        if new_seq > 99:
            new_seq = 1  # 溢出归1（极端情况）
        return today_base + new_seq
    else:
        # 新日期重置
        return today_base + 1


def parse_ip_list(text: str) -> list:
    """解析IP列表（支持逗号、分号、空格、换行分隔）

    Args:
        text: 输入文本，如 "8.8.8.8, 114.114.114.114\\n223.5.5.5"

    Returns:
        list: 清洗后的IP/地址字符串列表
    """
    if not text:
        return []
    ips = [ip.strip() for ip in re.split(r'[,;\s\n]+', text)]
    return [ip for ip in ips if ip]


def format_ip_list(ips: list) -> str:
    """将IP列表格式化为逗号分隔字符串

    Args:
        ips: IP字符串列表

    Returns:
        str: 逗号分隔字符串
    """
    return ', '.join(str(ip) for ip in ips if ip)


def reverse_ipv4(ip: str) -> str:
    """将IPv4地址转换为反向区域名称

    Example:
        reverse_ipv4('192.168.1.0') → '1.168.192.in-addr.arpa'
        reverse_ipv4('10.0.0.1') → '1.0.0.10.in-addr.arpa'

    Args:
        ip: IPv4地址字符串

    Raises:
        ValueError: 非法IPv4地址

    Returns:
        str: 反向区域名称
    """
    octets = ip.strip().split('.')
    if len(octets) != 4 or not all(0 <= int(o) <= 255 for o in octets if o.isdigit()):
        raise ValueError(f'无效的IPv4地址: {ip}')
    reversed_octets = list(reversed(octets))
    return '.'.join(reversed_octets) + '.in-addr.arpa'


def ipv4_to_reverse_zone(cidr: str) -> str:
    """根据CIDR计算反向区域名称

    要求掩码必须是8的倍数（BIND9要求完整octet对齐）。

    Examples:
        ipv4_to_reverse_zone('192.168.1.0/24') → '1.168.192.in-addr.arpa'
        ipv4_to_reverse_zone('10.0.0.0/8') → '10.in-addr.arpa'
        ipv4_to_reverse_zone('172.16.0.0/16') → '16.172.in-addr.arpa'

    Args:
        cidr: CIDR表示的网络地址

    Raises:
        ValueError: 掩码不是8的倍数或非法CIDR

    Returns:
        str: 反向区域名称
    """
    try:
        network = ipaddress.IPv4Network(cidr, strict=False)
    except (ValueError, ipaddress.AddressValueError):
        raise ValueError(f'无效的IPv4 CIDR: {cidr}')

    prefixlen = network.prefixlen

    if prefixlen % 8 != 0:
        raise ValueError(
            f'反向区域要求掩码为8的倍数，当前/{prefixlen}。'
            f'请使用 /{((prefixlen // 8) * 8)} 或 /{((prefixlen // 8 + 1) * 8)}'
        )

    octets_to_show = (32 - prefixlen) // 8
    network_str = str(network.network_address)
    octets = network_str.split('.')
    relevant_octets = octets[:octets_to_show]
    reversed_octets = list(reversed(relevant_octets))

    return '.'.join(reversed_octets) + '.in-addr.arpa'


def ipv6_to_reverse_zone(cidr: str) -> str:
    """根据IPv6 CIDR计算反向区域名称(IPv6 PTR)

    Examples:
        ipv6_to_reverse_zone('2001:db8::/32') → '8.b.d.0.1.0.0.2.ip6.arpa'
        ipv6_to_reverse_zone('fe80::/10') → '0.0.0.0.0.0.0.0.8.e.f.ip6.arpa'

    Args:
        cidr: IPv6 CIDR表示

    Raises:
        ValueError: 非法IPv6 CIDR

    Returns:
        str: IPv6反向区域名称
    """
    try:
        network = ipaddress.IPv6Network(cidr, strict=False)
    except (ValueError, ipaddress.AddressValueError):
        raise ValueError(f'无效的IPv6 CIDR: {cidr}')

    # BIND9 IPv6反向使用 nibble 格式（每4位一个标签）
    # /64 → 16 nibbles, /32 → 32 nibbles 等
    addr_int = int(network.network_address)
    # 计算需要多少个nibble
    nibble_count = (128 - network.prefixlen) // 4
    if (128 - network.prefixlen) % 4 != 0:
        raise ValueError(
            f'IPv6反向区域要求prefix是4的倍数，当前/{network.prefixlen}'
        )

    nibbles = []
    for i in range(nibble_count):
        nibbles.append(hex((addr_int >> (i * 4)) & 0xF)[1])

    return '.'.join(nibbles) + '.ip6.arpa'


def validate_soa_rname(rname: str) -> str:
    """验证和标准化SOA RNAME字段

    RFC规定: 管理员邮箱中的@用.替换

    Examples:
        validate_soa_rname('admin@example.com') → 'admin.example.com.'
        validate_soa_rname('admin.example.com.') → 'admin.example.com.'
        validate_soa_rname('hostmaster-dns') → 'hostmaster-dns.'  (无@则直接加尾点)

    Args:
        rname: 输入RNAME值

    Returns:
        str: 标准化后的RNAME（以.结尾）
    """
    rname = rname.strip()
    if not rname:
        return 'admin.example.com.'  # 默认安全值

    if '@' in rname:
        local, domain = rname.rsplit('@', 1)
        rname = f"{local}.{domain}"
    if not rname.endswith('.'):
        rname += '.'
    return rname


def get_record_help_text(record_type: str) -> str:
    """返回各记录类型的帮助提示文本

    Args:
        record_type: DNS记录类型 (SOA/NS/A/AAAA/CNAME/MX/PTR/TXT/SRV)

    Returns:
        str: 该记录类型的帮助提示文本
    """
    help_texts = {
        'SOA': (
            'SOA记录每区唯一，定义区域的权威信息。'
            '值格式: 主DNS服务器 管理邮箱(SOA序列号 刷新 重试 过期 最小TTL)。'
            '示例: ns1.example.com. admin.example.com. 2026042401 3600 600 86400 3600'
        ),
        'NS': (
            '名称服务器记录，指向该区域的权威DNS服务器。'
            '值必须是FQDN（以.结尾），如 ns1.example.com.'
        ),
        'A': (
            'IPv4地址记录，将域名映射到IPv4地址。'
            '值为合法IPv4，如 192.168.1.10'
        ),
        'AAAA': (
            'IPv6地址记录，将域名映射到IPv6地址。'
            '值为合法IPv6，如 2001:db8::1 或 fe80::1'
        ),
        'CNAME': (
            '别名记录，将一个域名指向另一个域名(CNAME目标)。'
            '注意：CNAME不能与同名其他类型记录并存(RFC规范)。'
            '值必须为FQDN，如 www.example.com.'
        ),
        'MX': (
            '邮件交换记录，指定域名的邮件服务器。'
            '值格式: 优先级 目标域名。优先级越小越优先(0-65535)。'
            '示例: 10 mail.example.com.'
        ),
        'PTR': (
            '指针记录，用于反向DNS查询(IP→域名)。'
            '值必须为FQDN，如 mail.example.com.'
        ),
        'TXT': (
            '文本记录，存储任意文本信息(SPFDKIM/验证等常用)。'
            '值需用双引号包裹可包含空格，如 "v=spf1 include:_spf.google.com ~all"'
        ),
        'SRV': (
            '服务定位记录，指定特定服务的服务器位置。'
            '值格式: 优先级 权重 端口 目标域名。'
            '示例: 0 5 5060 sipserver.example.com.'
        ),
    }
    return help_texts.get(record_type, '')


def validate_record_value(record_type: str, value: str) -> tuple:
    """校验各类型记录值的合法性

    Args:
        record_type: DNS记录类型
        value: 记录值

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not value:
        return False, '记录值不能为空'

    value = value.strip()

    if record_type == 'A':
        if not re.match(r'^(\d{1,3}\.){3}\d{1,3}$', value):
            return False, '无效的IPv4地址格式'
        octets = value.split('.')
        if any(int(o) > 255 for o in octets):
            return False, 'IPv4各段必须在0-255之间'

    elif record_type == 'AAAA':
        try:
            ipaddress.IPv6Address(value)
        except (ipaddress.AddressValueError, ValueError):
            return False, '无效的IPv6地址格式'

    elif record_type == 'CNAME':
        # CNAME目标必须是合法域名（通常为FQDN）
        normalized = value.rstrip('.')
        if '.' not in normalized and normalized != '@':
            return False, 'CNAME目标应为FQDN（包含至少一个点）'

    elif record_type == 'MX':
        parts = value.split(None, 1)
        if len(parts) < 2:
            return False, 'MX格式错误: 应为 "优先级 目标域名"，如 "10 mail.example.com."'
        try:
            prio = int(parts[0])
            if prio < 0 or prio > 65535:
                return False, 'MX优先级范围 0-65535'
        except ValueError:
            return False, 'MX优先级必须为整数'

    elif record_type == 'SRV':
        parts = value.split()
        if len(parts) < 4:
            return False, 'SRV格式错误: 应为 "优先级 权重 端口 目标"'
        try:
            for field_name, val, lo, hi in [
                ('优先级', parts[0], 0, 65535),
                ('权重', parts[1], 0, 65535),
                ('端口', parts[2], 1, 65535),
            ]:
                v = int(val)
                if v < lo or v > hi:
                    return False, f'SRV{field_name}范围 {lo}-{hi}，当前{v}'
        except ValueError:
            return False, 'SRV优先级/权重/端口必须为整数'

    elif record_type in ('NS', 'PTR'):
        # NS和PTR的目标应该是FQDN
        if not value.endswith('.') and '.' not in value:
            return False, f'{record_type}记录值应为FQDN（以.结尾或包含点）'

    return True, None
