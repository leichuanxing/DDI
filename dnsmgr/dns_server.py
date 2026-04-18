"""
轻量级 DNS 服务器实现
基于 Python Raw Socket，从数据库读取区域记录提供 DNS 解析服务
支持:
  - 本地正向/反向区域查询 (A, AAAA, CNAME, MX, TXT, NS, PTR)
  - 外部转发 (Forwarder) - 本地无记录时转发到上游DNS
  - 查询缓存 - 减少重复外部查询
  - 标准 DNS 协议解析与响应构建
"""

import socket
import struct
from django.db.models import Q
import threading
import time
import logging
import random

logger = logging.getLogger(__name__)

# DNS Query Type Codes
QTYPE_A = 1
QTYPE_AAAA = 28
QTYPE_CNAME = 5
QTYPE_MX = 15
QTYPE_TXT = 16
QTYPE_NS = 2
QTYPE_PTR = 12
QTYPE_SOA = 6
QTYPE_ANY = 255

# DNS Response Code
RCODE_NOERROR = 0
RCODE_FORMATERROR = 1
RCODE_SERVERFAILURE = 2
RCODE_NXDOMAIN = 3
RCODE_NOTIMP = 4
RCODE_REFUSED = 5

# DNS Record type name mapping
QTYPE_MAP = {
    'A': QTYPE_A,
    'AAAA': QTYPE_AAAA,
    'CNAME': QTYPE_CNAME,
    'MX': QTYPE_MX,
    'TXT': QTYPE_TXT,
    'NS': QTYPE_NS,
    'PTR': QTYPE_PTR,
    'SOA': QTYPE_SOA,
}

REVERSE_QTYPE = {v: k for k, v in QTYPE_MAP.items()}


class DNSServer:
    """轻量级 DNS 服务器"""

    def __init__(self):
        self.running = False
        self.server_socket = None
        self.thread = None
        self._start_time = None
        self._total_queries = 0
        self._cache = {}       # {domain_type: (answer_data, ttl, timestamp)}
        self._cache_lock = threading.Lock()
        # 当前配置
        self._forwarders = ['8.8.8.8', '114.114.114.114']
        self._enable_forward = True
        self._enable_cache = True
        self._cache_ttl = 300
        self._default_ttl = 3600

    @property
    def is_running(self):
        return self.running

    @property
    def uptime(self):
        if self._start_time:
            return int(time.time() - self._start_time)
        return 0

    @property
    def served_count(self):
        return self._total_queries

    @property
    def cache_size(self):
        with self._cache_lock:
            return len(self._cache)

    def get_status(self):
        """获取服务状态"""
        settings = self._load_settings()
        return {
            'running': self.running,
            'uptime': self.uptime,
            'total_queries': self._total_queries,
            'cache_size': self.cache_size,
            'forwarders': settings.get('forwarders', []),
            'enable_forward': settings.get('enable_forward', True),
            'enable_cache': settings.get('enable_cache', True),
            'listen_port': settings.get('listen_port', 53),
        }

    def _load_settings(self):
        """从数据库加载配置"""
        try:
            from .models import DNSSettings
            s = DNSSettings.get_settings()
            return {
                'forwarders': s.get_forwarder_list(),
                'enable_forward': s.enable_forward,
                'listen_port': s.listen_port,
                'listen_address': str(s.listen_address) or '0.0.0.0',
                'default_ttl': s.default_ttl,
                'enable_cache': s.enable_cache,
                'cache_ttl': s.cache_ttl,
            }
        except Exception as e:
            logger.error(f"加载DNS配置失败: {e}")
            return {
                'forwarders': ['8.8.8.8'],
                'enable_forward': True,
                'listen_port': 53,
                'listen_address': '0.0.0.0',
                'default_ttl': 3600,
                'enable_cache': True,
                'cache_ttl': 300,
            }

    def _reload_settings(self):
        """重新加载配置到内存"""
        s = self._load_settings()
        self._forwarders = s['forwarders']
        self._enable_forward = s['enable_forward']
        self._enable_cache = s['enable_cache']
        self._cache_ttl = s['cache_ttl']
        self._default_ttl = s['default_ttl']

    # ==================== DNS 包解析 ====================

    @staticmethod
    def parse_name(data, offset):
        """解析域名（支持指针压缩）"""
        labels = []
        original_offset = offset
        jumped = False
        max_jumps = 10

        while True:
            if offset >= len(data):
                break
            length = data[offset]
            if length == 0:
                offset += 1
                break
            # 指针压缩 (高2位为11)
            if (length & 0xC0) == 0xC0:
                if not jumped:
                    original_offset = offset + 2
                pointer = struct.unpack('!H', data[offset:offset+2])[0] & 0x3FFF
                offset = pointer
                jumped = True
                max_jumps -= 1
                if max_jumps <= 0:
                    break
                continue
            offset += 1
            labels.append(data[offset:offset + length].decode('ascii', errors='ignore'))
            offset += length

        name = '.'.join(labels).lower()
        return name, original_offset if jumped else offset

    def parse_dns_packet(self, data):
        """解析完整的 DNS 查询包"""
        if len(data) < 12:
            return None

        try:
            tid = struct.unpack('!H', data[0:2])[0]
            flags = struct.unpack('!H', data[2:4])[0]
            qdcount = struct.unpack('!H', data[4:6])[0]
            ancount = struct.unpack('!H', data[6:8])[0]

            is_response = (flags >> 15) & 1
            opcode = (flags >> 11) & 0xF
            rcode = flags & 0xF

            questions = []
            offset = 12
            for _ in range(qdcount):
                qname, offset = self.parse_name(data, offset)
                if offset + 4 > len(data):
                    break
                qtype = struct.unpack('!H', data[offset:offset+2])[0]
                qclass = struct.unpack('!H', data[offset+2:offset+4])[0]
                offset += 4
                questions.append({
                    'name': qname,
                    'qtype': qtype,
                    'qclass': qclass,
                })

            return {
                'tid': tid,
                'flags': flags,
                'is_response': is_response,
                'opcode': opcode,
                'rcode': rcode,
                'questions': questions,
            }
        except Exception as e:
            logger.debug(f"解析DNS包失败: {e}")
            return None

    # ==================== DNS 响应构建 ====================

    @staticmethod
    def encode_name(name):
        """编码域名为 DNS 格式"""
        result = b''
        for label in name.rstrip('.').split('.'):
            encoded_label = label.encode('ascii')
            result += bytes([len(encoded_label)]) + encoded_label
        result += b'\x00'
        return result

    def build_answer_rr(self, name, rtype, rdata, ttl=3600):
        """构建一条资源记录 (Resource Record)"""
        rr = self.encode_name(name)
        rr += struct.pack('!HHIH', rtype, 1, ttl, len(rdata))
        rr += rdata
        return rr

    def build_a_record(self, ip_str, ttl=3600):
        """构建 A 记录数据部分"""
        parts = [int(p) for p in ip_str.split('.')]
        return bytes(parts)

    def build_aaaa_record(self, addr_str, ttl=3600):
        """构建 AAAA 记录数据部分"""
        import socket as s
        return s.inet_pton(socket.AF_INET6, addr_str)

    def build_ptr_record(self, target_name, ttl=3600):
        """构建 PTR 记录数据部分 (目标域名)"""
        return self.encode_name(target_name)

    def build_cname_record(self, target_name, ttl=3600):
        """构建 CNAME 记录数据部分"""
        return self.encode_name(target_name)

    def build_mx_record(self, preference, exchange, ttl=3600):
        """构建 MX 记录数据部分"""
        return struct.pack('!H', preference) + self.encode_name(exchange)

    def build_txt_record(self, text, ttl=3600):
        """构建 TXT 记录数据部分"""
        text_bytes = text.encode('utf-8')
        return bytes([len(text_bytes)]) + text_bytes

    def build_ns_record(self, ns_name, ttl=3600):
        """构建 NS 记录数据部分"""
        return self.encode_name(ns_name)

    def build_soa_record(self, mname, rname, serial, refresh, retry, expire, minimum, ttl=3600):
        """构建 SOA 记录数据"""
        data = self.encode_name(mname)
        data += self.encode_name(rname)
        data += struct.pack('!IIIII', serial, refresh, retry, expire, minimum)
        return data

    def build_dns_response(self, query, answers=None, authority=None, additional=None,
                           rcode=RCODE_NOERROR, aa_flag=False):
        """构建完整的 DNS 响应包"""
        if answers is None:
            answers = []
        if authority is None:
            authority = []
        if additional is None:
            additional = []

        tid = query['tid']
        flags = 0x8000  # QR=1 (response), opcode=0(standard)
        if aa_flag:
            flags |= 0x0400  # AA flag (authoritative answer)
        flags |= rcode

        response = bytearray()
        # Header
        response += struct.pack('!H', tid)
        response += struct.pack('!H', flags)
        response += struct.pack('!HHHH',
                                len(query['questions']),  # QDCOUNT
                                len(answers),              # ANCOUNT
                                len(authority),           # NSCOUNT
                                len(additional))          # ARCOUNT

        # Question section (echo back)
        for q in query['questions']:
            response += self.encode_name(q['name'])
            response += struct.pack('!HH', q['qtype'], q['qclass'])

        # Answer section
        for ans in answers:
            response += ans

        # Authority section
        for auth in authority:
            response += auth

        # Additional section
        for add in additional:
            response += add

        return bytes(response)

    # ==================== 本地查询 ====================

    def _get_best_record(self, zone, local_name, record_type):
        """
        获取最优DNS记录（按优先级最小值选取）
        规则：
        - 同名称+类型的记录中，按优先级升序排列
        - 排除手动禁用的(status=disabled)记录
        - 如果记录关联了探测端口(probe_port)，则要求对应探测任务的最新状态为reachable
        - 返回第一条满足所有条件的记录，无则返回None
        """
        from django.db.models import Q as DjangoQ
        from .models import DNSRecord, ProbeTask

        # 匹配记录名（支持 @ 和空名等价），排除手动禁用的记录
        # 注意：不排除 invalid 状态！因为 invalid 可能是旧数据，
        # 实际有效性由探测任务实时状态决定
        records = zone.records.filter(
            record_type=record_type,
        ).exclude(
            status='disabled',
        ).filter(
            DjangoQ(name__iexact=local_name) | DjangoQ(name='@' if local_name == '' else local_name)
        )

        # 按优先级升序排列
        candidates = list(records.order_by('priority', 'id'))

        if not candidates:
            return None

        # 检查哪些记录关联了探测任务，并查询其可达性
        # 匹配策略：先尝试 (target, port) 精确匹配；若失败则回退到仅端口匹配
        probe_ports_needed = set()
        for r in candidates:
            if r.probe_port:
                probe_ports_needed.add(r.probe_port)

        reachable_probe_keys = set()   # (target, port) 精确匹配集合
        reachable_ports_only = set()   # 仅端口的回退匹配集合
        if probe_ports_needed:
            targets_to_check = set()
            for r in candidates:
                if r.probe_port:
                    tip = r.value.strip() if r.record_type in ('A', 'AAAA') else ''
                    if tip:
                        targets_to_check.add(tip)

            # 精确匹配：(target + port) 都要对应上
            if targets_to_check:
                probe_results = ProbeTask.objects.filter(
                    target__in=targets_to_check,
                    port__in=probe_ports_needed,
                    status='running',
                    last_status='reachable',
                ).values_list('target', 'port')
                reachable_probe_keys = set(probe_results)

            # 回退匹配：只要端口对应的任意探测任务可达即可
            # （覆盖场景：DNS记录value与ProbeTarget.target不完全一致的case）
            port_results = ProbeTask.objects.filter(
                port__in=probe_ports_needed,
                status='running',
                last_status='reachable',
            ).values_list('port', flat=True).distinct()
            reachable_ports_only = set(port_results)

            logger.debug(f"[DNS探测匹配] 端口{probe_ports_needed} -> "
                        f"精确匹配:{reachable_probe_keys}, 端口回退:{reachable_ports_only}")

        # 遍历按优先级排序的候选，返回第一个有效的
        for rec in candidates:
            if rec.probe_port:
                target_ip = rec.value.strip() if rec.record_type in ('A', 'AAAA') else ''
                probe_key = (target_ip, rec.probe_port)

                # 优先检查精确匹配
                if probe_key in reachable_probe_keys:
                    logger.debug(f"[DNS命中-精确] {rec.name} {rec.record_type} -> {rec.value} "
                                f"(priority={rec.priority}, 探测{probe_key} 可达)")
                    return rec

                # 回退：仅端口匹配
                if rec.probe_port in reachable_ports_only:
                    logger.info(f"[DNS命中-端口回退] {rec.name} {rec.record_type} -> {rec.value} "
                              f"(priority={rec.priority}, 端口{rec.probe_port}可达, "
                              f"但target不匹配: rec_value={target_ip})")
                    return rec

                # 探测不可达，跳过
                logger.warning(f"[DNS跳过] {rec.name} {rec.record_type} -> {rec.value} "
                              f"(priority={rec.priority}, 探测端口{rec.probe_port} 不可达)")
                continue

            # 无探测关联，直接返回
            logger.info(f"[DNS命中-无探测] {rec.name} {rec.record_type} -> {rec.value} "
                       f"(priority={rec.priority})")
            return rec

        # 所有候选记录都不可达
        return None

    def lookup_local(self, qname, qtype):
        """
        在本地数据库中查找 DNS 记录
        返回: list of (raw_rr_bytes) 或 None (表示无结果，需要转发或返回NXDOMAIN)
        """
        from .models import DNSZone, DNSRecord
        results = []

        try:
            # === PTR 反向查找 ===
            if qtype == QTYPE_PTR and qname.endswith('.in-addr.arpa'):
                # 从反向域名中提取IP: 100.168.192.in-addr.arpa -> 192.168.100.100
                ptr_part = qname.replace('.in-addr.arpa', '')
                ip_parts = ptr_part.split('.')[::-1]
                if len(ip_parts) == 4:
                    ip_addr = '.'.join(ip_parts)

                    # 在所有正向区域的A记录中查找匹配的IP
                    forward_zones = DNSZone.objects.filter(zone_type='forward')
                    for zone in forward_zones:
                        records = zone.records.filter(
                            record_type='A',
                            value=ip_addr,
                            status='enabled'
                        )
                        for rec in records[:10]:
                            fqdn = rec.get_fqdn()
                            rdata = self.build_ptr_record(fqdn)
                            results.append(
                                self.build_answer_rr(qname, QTYPE_PTR, rdata,
                                                   rec.ttl or self._default_ttl)
                            )
                            logger.info(f"[DNS本地-PTR] {qname} -> {fqdn}")
                    return results if results else None

            # === 正向查找 ===
            # 遍历所有正向区域，找到匹配的区域
            zones = DNSZone.objects.filter(zone_type='forward')
            matched_zone = None
            domain_suffix = qname

            while '.' in domain_suffix:
                z = zones.filter(name=domain_suffix).first()
                if z:
                    matched_zone = z
                    break
                domain_suffix = domain_suffix.split('.', 1)[1] if '.' in domain_suffix else ''

            if not matched_zone:
                return None  # 不属于任何本地区域

            # 确定要查询的记录名
            if qname == matched_zone.name:
                local_name = '@'
            elif qname.endswith('.' + matched_zone.name):
                local_name = qname[:-(len(matched_zone.name) + 1)]
            else:
                local_name = qname

            # 查询记录（按优先级最小值选取最优记录）
            if qtype == QTYPE_A:
                rec = self._get_best_record(matched_zone, local_name, 'A')
                if rec:
                    rdata = self.build_a_record(rec.value)
                    results.append(
                        self.build_answer_rr(qname, QTYPE_A, rdata,
                                           rec.ttl or self._default_ttl)
                    )
                    logger.info(f"[DNS本地-A] {qname} -> {rec.value} (priority={rec.priority})")

            elif qtype == QTYPE_AAAA:
                rec = self._get_best_record(matched_zone, local_name, 'AAAA')
                if rec:
                    rdata = self.build_aaaa_record(rec.value)
                    results.append(
                        self.build_answer_rr(qname, QTYPE_AAAA, rdata,
                                           rec.ttl or self._default_ttl)
                    )

            elif qtype == QTYPE_CNAME:
                rec = self._get_best_record(matched_zone, local_name, 'CNAME')
                if rec:
                    rdata = self.build_cname_record(rec.value)
                    results.append(
                        self.build_answer_rr(qname, QTYPE_CNAME, rdata,
                                           rec.ttl or self._default_ttl)
                    )
                    logger.info(f"[DNS本地-CNAME] {qname} -> {rec.value} (priority={rec.priority})")

            elif qtype == QTYPE_MX:
                rec = self._get_best_record(matched_zone, local_name, 'MX')
                if rec:
                    parts = rec.value.split()
                    pref = int(parts[0]) if parts else 10
                    exchange = parts[1] if len(parts) > 1 else rec.value
                    rdata = self.build_mx_record(pref, exchange)
                    results.append(
                        self.build_answer_rr(qname, QTYPE_MX, rdata,
                                           rec.ttl or self._default_ttl)
                    )

            elif qtype == QTYPE_TXT:
                rec = self._get_best_record(matched_zone, local_name, 'TXT')
                if rec:
                    rdata = self.build_txt_record(rec.value)
                    results.append(
                        self.build_answer_rr(qname, QTYPE_TXT, rdata,
                                           rec.ttl or self._default_ttl)
                    )

            elif qtype == QTYPE_NS:
                rec = self._get_best_record(matched_zone, local_name, 'NS')
                if rec:
                    rdata = self.build_ns_record(rec.value)
                    results.append(
                        self.build_answer_rr(qname, QTYPE_NS, rdata,
                                           rec.ttl or self._default_ttl)
                    )

            elif qtype == QTYPE_ANY or qtype == QTYPE_SOA:
                # ANY查询：返回该名称下每种类型的最优记录（按优先级最小）
                for rtype in ('A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS'):
                    rec = self._get_best_record(matched_zone, local_name, rtype)
                    if not rec:
                        continue
                    rt = QTYPE_MAP.get(rtype)
                    if not rt:
                        continue
                    if rec.record_type == 'A':
                        rd = self.build_a_record(rec.value)
                    elif rec.record_type == 'AAAA':
                        rd = self.build_aaaa_record(rec.value)
                    elif rec.record_type == 'CNAME':
                        rd = self.build_cname_record(rec.value)
                    elif rec.record_type == 'MX':
                        p = rec.value.split()
                        rd = self.build_mx_record(int(p[0]), p[1])
                    elif rec.record_type == 'TXT':
                        rd = self.build_txt_record(rec.value)
                    elif rec.record_type == 'NS':
                        rd = self.build_ns_record(rec.value)
                    elif rec.record_type == 'PTR':
                        rd = self.build_ptr_record(rec.value)
                    else:
                        continue
                    results.append(
                        self.build_answer_rr(qname, rt, rd,
                                           rec.ttl or self._default_ttl)
                    )

            return results if results else None

        except Exception as e:
            logger.error(f"本地DNS查询异常: {e}")
            return None

    # ==================== 外部转发 ====================

    def _check_cache(self, qname, qtype):
        """检查缓存"""
        with self._cache_lock:
            key = f"{qname}|{qtype}"
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry[2] < entry[1]:  # TTL未过期
                    return entry[0]
                del self._cache[key]
        return None

    def _set_cache(self, qname, qtype, answer_data):
        """写入缓存"""
        if not self._enable_cache:
            return
        with self._cache_lock:
            key = f"{qname}|{qtype}"
            self._cache[key] = (answer_data, self._cache_ttl, time.time())
            # 缓存大小限制
            if len(self._cache) > 5000:
                # 清除最旧的50%
                sorted_items = sorted(self._cache.items(), key=lambda x: x[1][2])
                for k, _ in sorted_items[:len(sorted_items)//2]:
                    del self._cache[k]

    def forward_query(self, query, qname, qtype):
        """
        将查询转发到上游 DNS 服务器
        返回: (response_bytes, success)
        """
        # 先查缓存
        cached = self._check_cache(qname, qtype)
        if cached is not None:
            logger.info(f"[DNS缓存命中] {qname} ({REVERSE_QTYPE.get(qtype, qtype)})")
            return cached, True

        if not self._enable_forward or not self._forwarders:
            return None, False

        # 构建原始请求包
        request_data = bytearray()
        request_data += struct.pack('!H', query['tid'])
        request_data += struct.pack('!H', 0x0100)  # RD=1 (递归期望)
        request_data += struct.pack('!HHHH', 1, 0, 0, 0)
        request_data += self.encode_name(qname)
        request_data += struct.pack('!HH', qtype, 1)  # QTYPE, CLASS IN
        request_data = bytes(request_data)

        # 尝试各个转发器
        for forwarder in self._forwarders:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(3.0)
                sock.sendto(request_data, (forwarder, 53))

                response, _ = sock.recvfrom(4096)
                sock.close()

                # 解析验证响应ID是否匹配
                if len(response) >= 12:
                    resp_tid = struct.unpack('!H', response[0:2])[0]
                    if resp_tid == query['tid']:
                        # 写入缓存（只缓存answer部分）
                        self._set_cache(qname, qtype, response)

                        # 解析ancount确认有答案
                        ancount = struct.unpack('!H', response[6:8])[0]
                        rcode_val = response[3] & 0xF
                        rcode_name = ['NOERR', 'FORMERR', 'SERVFAIL', 'NXDOMAIN',
                                     'NOTIMP', 'REFUSED'][rcode_val] if rcode_val < 6 else str(rcode_val)
                        logger.info(f"[DNS转发-{rcode_name}] {qname} -> "
                                   f"{forwarder} (answers={ancount})")
                        return response, True
            except socket.timeout:
                logger.debug(f"转发器 {forwarder} 超时")
                continue
            except Exception as e:
                logger.warning(f"转发到 {forwarder} 失败: {e}")
                continue

        logger.warning(f"[DNS转发失败] {qname} 所有转发器均无响应")
        return None, False

    # ==================== 主处理循环 ====================

    def _write_log(self, qname, qtype, client_ip, result_source, answer_data='',
                    rcode=0, elapsed_ms=0):
        """异步写日志（不阻塞主线程）"""
        import json
        try:
            from .models import DNSQueryLog
            DNSQueryLog.create_log(
                query_name=qname,
                query_type=REVERSE_QTYPE.get(qtype, str(qtype)),
                client_ip=client_ip,
                result_source=result_source,
                answer_data=json.dumps(answer_data) if isinstance(answer_data, dict) else str(answer_data),
                rcode=rcode,
                response_time_ms=elapsed_ms,
            )
        except Exception as e:
            logger.debug(f"写入DNS日志失败: {e}")

    def _handle_client(self, data, client_addr):
        """处理一个DNS查询"""
        import time as _time
        t_start = _time.time()

        query = self.parse_dns_packet(data)
        if not query or not query['questions']:
            return

        self._total_queries += 1
        q = query['questions'][0]
        qname = q['name'].lower().rstrip('.')  # 标准化域名
        qtype = q['qtype']
        type_name = REVERSE_QTYPE.get(qtype, str(qtype))
        client_ip = client_addr[0]

        logger.info(f"[DNS查询] {client_ip}:{client_addr[1]} "
                   f"{qname} [{type_name}]")

        # 1. 先在本地查找
        local_answers = self.lookup_local(qname, qtype)

        if local_answers is not None and len(local_answers) > 0:
            # 本地命中 - 提取答案摘要
            answer_ips = []
            for ans in local_answers:
                rd = self._extract_answer_rdata(ans, qtype)
                if rd:
                    answer_ips.append(rd)
            elapsed = (_time.time() - t_start) * 1000

            response = self.build_dns_response(query, answers=local_answers,
                                              rcode=RCODE_NOERROR, aa_flag=True)
            self._send_response(response, client_addr)
            self._write_log(qname, qtype, client_ip, 'local',
                          {'summary': ', '.join(answer_ips)},
                          rcode=RCODE_NOERROR, elapsed_ms=round(elapsed, 2))
            return

        # 2. 本地无记录但属于本地区域 → NXDOMAIN
        from .models import DNSZone
        try:
            is_local_domain = False
            zones = DNSZone.objects.filter(zone_type='forward')
            suffix = qname
            while '.' in suffix:
                if zones.filter(name=suffix).exists():
                    is_local_domain = True
                    break
                suffix = suffix.split('.', 1)[1] if '.' in suffix else ''

            if is_local_domain:
                # 属于本地区域但无记录 → NXDOMAIN
                response = self.build_dns_response(query, rcode=RCODE_NXDOMAIN,
                                                  aa_flag=True)
                self._send_response(response, client_addr)
                elapsed = (_time.time() - t_start) * 1000
                logger.info(f"[DNS-NXDOMAIN] {qname} (本地无此记录)")
                self._write_log(qname, qtype, client_ip, 'nxdomain',
                              {'summary': 'NXDOMAIN (本地无记录)'},
                              rcode=RCODE_NXDOMAIN, elapsed_ms=round(elapsed, 2))
                return
        except Exception:
            pass

        # 3. 不属于任何本地区域 → 转发到上游
        forwarded_resp, success = self.forward_query(query, qname, qtype)
        elapsed = (_time.time() - t_start) * 1000

        if success and forwarded_resp:
            # 从转发响应中提取answer摘要
            summary = self._extract_forward_summary(forwarded_resp)
            source = 'cache' if self._check_cache(qname, qtype) else 'forward'
            self._send_response(forwarded_resp, client_addr)
            self._write_log(qname, qtype, client_ip, source, summary,
                          rcode=RCODE_NOERROR, elapsed_ms=round(elapsed, 2))
        else:
            # 转发也失败，返回 SERVFAIL
            response = self.build_dns_response(query, rcode=RCODE_SERVERFAULT)
            self._send_response(response, client_addr)
            logger.warning(f"[DNS-SERVFAIL] {qname} 转发失败")
            self._write_log(qname, qtype, client_ip, 'servfail',
                          {'summary': 'SERVFAIL (所有转发器失败)'},
                          rcode=RCODE_SERVERFAULT, elapsed_ms=round(elapsed, 2))

    @staticmethod
    def _extract_answer_rdata(rr_bytes, qtype):
        """从RR字节中提取rdata的可读摘要"""
        try:
            pos = 0
            # 跳过 name
            while rr_bytes[pos] != 0:
                length = rr_bytes[pos]
                if (length & 0xC0) == 0xC0:  # pointer
                    pos += 2
                    break
                pos += 1 + length
            else:
                pos += 1  # skip \x00
            pos += 4  # TYPE(2) + CLASS(2)
            pos += 4  # TTL(4)
            rdlength = struct.unpack('!H', rr_bytes[pos:pos+2])[0]
            pos += 2
            rdata = rr_bytes[pos:pos+rdlength]
            
            if qtype == QTYPE_A and len(rdata) >= 4:
                return '.'.join(str(b) for b in rdata[:4])
            elif qtype == QTYPE_PTR or qtype == QTYPE_CNAME or qtype == QTYPE_NS:
                name, _ = DNSServer.parse_name(rdata, 0)
                return name
            elif qtype == QTYPE_MX and len(rdata) > 2:
                pref = struct.unpack('!H', rdata[:2])[0]
                name, _ = DNSServer.parse_name(rdata, 2)
                return f"{pref} {name}"
            elif qtype == QTYPE_TXT:
                txt_len = rdata[0] if len(rdata) > 0 else 0
                return rdata[1:1+txt_len].decode('utf-8', errors='ignore')[:80]
        except (IndexError, ValueError):
            pass
        return None

    @staticmethod
    def _extract_forward_summary(resp_bytes):
        """从转发响应中提取摘要"""
        try:
            ancount = struct.unpack('!H', resp_bytes[6:8])[0]
            rcode_val = resp_bytes[3] & 0xF
            if rcode_val != 0:
                rcodes = {0:'NOERR', 3:'NXDOMAIN', 2:'SERVFAIL'}
                return {'summary': f'{rcodes.get(rcode_val, str(rcode_val))}'}
            if ancount <= 0:
                return {'summary': 'NOERR (空回答)'}
            # 简单提取第一个A记录的IP
            data = resp_bytes[12:]
            answers_found = 0
            ip_list = []
            pos = 0
            # 跳过question section
            for _ in range(1):  # only 1 question
                while pos < len(data) and data[pos] != 0:
                    if (data[pos] & 0xC0) == 0xC0:
                        pos += 2
                        break
                    pos += 1 + data[pos]
                else:
                    pos += 1  # \x00
                pos += 4   # QTYPE + QCLASS
            # 解析answers
            for _ in range(min(ancount, 10)):
                if pos >= len(data):
                    break
                if (data[pos] & 0xC0) == 0xC0:
                    pos += 2
                else:
                    while pos < len(data) and data[pos] != 0:
                        pos += 1 + data[pos]
                    pos += 1
                if pos + 10 > len(data):
                    break
                rtype = struct.unpack('!H', data[pos:pos+2])[0]; pos += 2
                pos += 2  # class
                pos += 4  # ttl
                rdlen = struct.unpack('!H', data[pos:pos+2])[0]; pos += 2
                rdata = data[pos:pos+rdlen]; pos += rdlen
                if rtype == 1 and len(rdata) >= 4:  # A
                    ip_list.append('.'.join(str(b) for b in rdata[:4]))
            if ip_list:
                return {'summary': ', '.join(ip_list)}
            return {'summary': f'NOERR ({ancount}条记录)'}
        except Exception:
            return {'summary': '(解析异常)'}

    def _send_response(self, data, client_addr):
        """发送 DNS 响应"""
        try:
            self.server_socket.sendto(data, client_addr)
        except Exception as e:
            logger.error(f"发送DNS响应失败: {e}")

    def _run(self):
        """主监听循环"""
        settings = self._load_settings()
        listen_addr = settings['listen_address']
        port = settings['listen_port']

        logger.info(f"DNS服务启动，监听 {listen_addr}:{port}, "
                   f"转发器: {self._forwarders}")

        buffer_size = 4096
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                data, addr = self.server_socket.recvfrom(buffer_size)
                if data:
                    self._handle_client(data, addr)
            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    logger.error(f"Socket错误: {e}")
                break
            except Exception as e:
                logger.error(f"处理DNS请求异常: {e}")

        logger.info("DNS服务已停止")

    def start(self, bind_ip='0.0.0.0', bind_port=53):
        """启动 DNS 服务"""
        if self.running:
            return False, "DNS服务已在运行中"

        try:
            # 加载最新配置
            self._reload_settings()
            bind_ip_from_cfg = self._load_settings().get('listen_address', bind_ip) or bind_ip
            bind_port_from_cfg = self._load_settings().get('listen_port', bind_port) or bind_port

            # 创建 UDP socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            self.server_socket.bind((str(bind_ip_from_cfg), bind_port_from_cfg))

            self.running = True
            self._start_time = time.time()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

            fwd_info = ', '.join(self._forwarders) if self._forwarders else '(无)'
            return True, f"DNS服务已启动 | 监听端口: {bind_port_from_cfg} | " \
                        f"转发器: {fwd_info}"

        except PermissionError:
            return False, "权限不足！端口53需要root权限运行 (sudo)"
        except OSError as e:
            err_msg = str(e)
            if 'Permission' in err_msg or 'Operation not permitted' in err_msg:
                return False, "权限不足！端口53需要root权限 (请用 sudo 启动服务)"
            if 'Address already in use' in err_msg:
                return False, f"端口{bind_port_from_cfg}已被占用，可能其他DNS服务正在运行"
            return False, f"启动失败: {err_msg}"
        except Exception as e:
            return False, f"启动异常: {e}"

    def stop(self):
        """停止 DNS 服务"""
        if not self.running:
            return False, "DNS服务未在运行"

        self.running = False

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

        info = f"已停止，累计处理 {self._total_queries} 次查询"
        self._start_time = None
        return True, info


# 全局单例
_dns_server_instance = None
_instance_lock = threading.Lock()


def get_dns_server():
    """获取全局 DNS 服务实例"""
    global _dns_server_instance
    with _instance_lock:
        if _dns_server_instance is None:
            _dns_server_instance = DNSServer()
        return _dns_server_instance
