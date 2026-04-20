"""
轻量级 DHCP 服务器实现
基于 Python Raw Socket，从数据库读取地址池配置对外提供 DHCP 服务
支持: DHCP Discover -> Offer -> Request -> Ack 标准流程
"""

import socket
import struct
import random
import time
import threading
import logging
import ipaddress

logger = logging.getLogger(__name__)

# DHCP 消息类型
DHCP_DISCOVER = 1
DHCP_OFFER = 2
DHCP_REQUEST = 3
DHCP_DECLINE = 4
DHCP_ACK = 5
DHCP_NAK = 6
DHCP_RELEASE = 7
DHCP_INFORM = 8

# DHCP Option Tags
OPTION_SUBNET_MASK = 1
OPTION_ROUTERS = 3
OPTION_DNS_SERVERS = 6
OPTION_LEASE_TIME = 51
OPTION_MESSAGE_TYPE = 53
OPTION_SERVER_ID = 54
OPTION_PARAM_REQ_LIST = 55
OPTION_END = 255


class DHCPServer:
    """轻量级 DHCP 服务器"""

    def __init__(self):
        self.running = False
        self.server_socket = None
        self.thread = None
        self._allocated_ips = {}  # mac -> ip_address (内存中已分配)
        self._lock = threading.Lock()
        self._start_time = None
        self._total_served = 0

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
        return self._total_served

    @property
    def allocated_count(self):
        return len(self._allocated_ips)

    def get_status(self):
        """获取服务状态"""
        pools = self._get_active_pools()
        return {
            'running': self.running,
            'uptime': self.uptime,
            'total_pools': len(pools),
            'served': self._total_served,
            'active_leases': len(self._allocated_ips),
            'pools': [
                {
                    'name': p.name,
                    'subnet': p.subnet.cidr,
                    'range': f'{p.start_address}-{p.end_address}',
                    'status': p.status,
                }
                for p in pools
            ]
        }

    def _get_active_pools(self):
        """获取所有启用的地址池"""
        try:
            from .models import DHCPPool
            return list(DHCPPool.objects.filter(status='enabled').select_related('subnet'))
        except Exception as e:
            logger.error(f"获取DHCP地址池失败: {e}")
            return []

    def _find_pool_for_subnet(self, subnet_cidr):
        """根据子网CIDR查找匹配的地址池"""
        pools = self._get_active_pools()
        for pool in pools:
            if pool.subnet.cidr == subnet_cidr:
                return pool
        return None

    def _is_ip_excluded(self, pool, ip):
        """检查IP是否在地址池的排除范围内"""
        return self._is_ip_excluded_fresh(pool.id, ip)

    def _is_ip_excluded_fresh(self, pool_id, ip):
        """★ 实时从数据库查询IP是否被排除/保留 — raw SQL绕过ORM缓存"""
        try:
            import ipaddress as ia_mod
            ip_int = int(ia_mod.ip_address(ip))
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT start_ip, end_ip FROM dhcpmgr_dhcpexclusion WHERE pool_id = %s",
                    [pool_id]
                )
                for row in cursor.fetchall():
                    start = int(ia_mod.ip_address(row[0]))
                    end = int(ia_mod.ip_address(row[1]))
                    if start <= ip_int <= end:
                        logger.info(f"[排除检测] IP={ip} 在 {row[0]}-{row[1]} 内")
                        return True
        except Exception as e:
            logger.error(f"[排除检测异常] pool={pool_id} ip={ip}: {e}")
        return False

    def _find_pool_for_ip(self, pools, ip):
        """根据IP地址查找所属的地址池（异常安全）"""
        try:
            import ipaddress as ia
            for p in pools:
                net = ia.ip_network(p.subnet.cidr, strict=False)
                if ia.ip_address(ip) in net:
                    return p
        except Exception as e:
            logger.error(f"[查找地址池失败] ip={ip}: {e}")
        return None

    def _build_nak(self, packet, server_ip='0.0.0.0'):
        """构建 DHCP NAK 响应包"""
        nak_data = bytearray(576)
        nak_data[0] = 2  # BOOTREPLY
        nak_data[4:8] = struct.pack('!I', packet['xid'])
        nak_data[28:34] = packet['chaddr'][:6]
        pos = 236
        nak_data[pos:pos + 4] = struct.pack('!I', 0x63825363); pos += 4
        nak_data[pos] = OPTION_MESSAGE_TYPE; pos += 1
        nak_data[pos] = 1; pos += 1
        nak_data[pos] = DHCP_NAK; pos += 1
        nak_data[pos] = OPTION_SERVER_ID; pos += 1
        nak_data[pos] = 4; pos += 1
        srv_b = bytes(int(b) for b in server_ip.split('.'))
        nak_data[pos:pos + 4] = srv_b; pos += 4
        nak_data[pos] = OPTION_END
        return bytes(nak_data)

    def _get_available_ip(self, pool):
        """从地址池中获取一个可用IP（实时SQL查排除列表，绕过ORM缓存）"""
        import ipaddress
        start = int(ipaddress.ip_address(pool.start_address))
        end = int(ipaddress.ip_address(pool.end_address))

        used_ips = set(self._allocated_ips.values())

        # ★ 实时SQL查询排除范围
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT start_ip, end_ip FROM dhcpmgr_dhcpexclusion WHERE pool_id = %s",
                    [pool.id]
                )
                for row in cursor.fetchall():
                    es = int(ipaddress.ip_address(row[0]))
                    ee = int(ipaddress.ip_address(row[1]))
                    for i in range(es, ee + 1):
                        used_ips.add(str(ipaddress.ip_address(i)))
        except Exception as e:
            logger.error(f"获取排除范围失败(pool_id={pool.id}): {e}")

        available = []
        for i in range(start, end + 1):
            ip_str = str(ipaddress.ip_address(i))
            if ip_str not in used_ips:
                available.append(ip_str)

        if not available:
            return None
        return random.choice(available)

    def _parse_dhcp_packet(self, data):
        """解析 DHCP 数据包"""
        if len(data) < 240:
            return None
        try:
            op = data[0]
            htype = data[1]
            hlen = data[2]
            hops = data[3]
            xid = struct.unpack('!I', data[4:8])[0]
            secs = struct.unpack('!H', data[8:10])[0]
            flags = struct.unpack('!H', data[10:12])[0]
            ciaddr = '.'.join(str(b) for b in data[12:16])
            yiaddr = '.'.join(str(b) for b in data[16:20])
            siaddr = '.'.join(str(b) for b in data[20:24])
            giaddr = '.'.join(str(b) for b in data[24:28])
            chaddr = data[28:34 + hlen]

            options = {}
            pos = 236
            magic_cookie = struct.unpack('!I', data[pos:pos + 4])[0]
            pos += 4
            if magic_cookie != 0x63825363:
                return None
            while pos < len(data):
                opt_type = data[pos]
                if opt_type == OPTION_END:
                    break
                pos += 1
                if pos >= len(data):
                    break
                opt_len = data[pos]
                pos += 1
                opt_data = data[pos:pos + opt_len]
                options[opt_type] = opt_data
                pos += opt_len
            return {
                'op': op, 'htype': htype, 'hlen': hlen, 'xid': xid,
                'secs': secs, 'flags': flags, 'ciaddr': ciaddr,
                'yiaddr': yiaddr, 'siaddr': siaddr, 'giaddr': giaddr,
                'chaddr': chaddr, 'options': options,
            }
        except Exception as e:
            logger.debug(f"解析DHCP包失败: {e}")
            return None

    def _build_dhcp_response(self, request, msg_type, offered_ip, pool, server_ip='0.0.0.0'):
        """构建 DHCP 响应包"""
        import ipaddress
        network = ipaddress.ip_network(pool.subnet.cidr, strict=False)
        netmask = str(network.netmask)
        response = bytearray(576)

        response[0] = 2  # BOOTREPLY
        response[1] = request['htype']
        response[2] = request['hlen']
        response[3] = 0
        response[4:8] = struct.pack('!I', request['xid'])
        response[8:10] = struct.pack('!H', 0)
        response[10:12] = struct.pack('!H', request['flags'])

        if offered_ip and offered_ip != '0.0.0.0':
            ip_bytes = bytes(int(b) for b in offered_ip.split('.'))
            response[16:20] = ip_bytes

        siaddr_bytes = bytes(int(b) for b in server_ip.split('.'))
        response[20:24] = siaddr_bytes

        if request['giaddr'] != '0.0.0.0':
            giaddr_bytes = bytes(int(b) for b in request['giaddr'].split('.'))
            response[24:28] = giaddr_bytes

        chaddr_len = min(len(request['chaddr']), 16)
        response[28:28 + chaddr_len] = request['chaddr'][:chaddr_len]

        pos = 236
        response[pos:pos + 4] = struct.pack('!I', 0x63825363); pos += 4

        # Option 53: Message Type
        response[pos] = OPTION_MESSAGE_TYPE; pos += 1
        response[pos] = 1; pos += 1
        response[pos] = msg_type; pos += 1

        # Option 1: Subnet Mask
        mask_bytes = bytes(int(b) for b in netmask.split('.'))
        response[pos] = OPTION_SUBNET_MASK; pos += 1
        response[pos] = 4; pos += 1
        response[pos:pos + 4] = mask_bytes; pos += 4

        # Option 3: Router/Gateway
        if pool.gateway:
            gw_bytes = bytes(int(b) for b in pool.gateway.split('.'))
            response[pos] = OPTION_ROUTERS; pos += 1
            response[pos] = 4; pos += 1
            response[pos:pos + 4] = gw_bytes; pos += 4

        # Option 6: DNS Servers
        if pool.dns_servers:
            dns_list = [s.strip() for s in pool.dns_servers.split(',') if s.strip()]
            dns_bytes = b''
            for dns in dns_list[:4]:
                dns_bytes += bytes(int(b) for b in dns.split('.'))
            if dns_bytes:
                response[pos] = OPTION_DNS_SERVERS; pos += 1
                response[pos] = len(dns_bytes); pos += 1
                response[pos:pos + len(dns_bytes)] = dns_bytes; pos += len(dns_bytes)

        # Option 51: Lease Time
        lease_bytes = struct.pack('!I', pool.lease_time)
        response[pos] = OPTION_LEASE_TIME; pos += 1
        response[pos] = 4; pos += 1
        response[pos:pos + 4] = lease_bytes; pos += 4

        # Option 54: Server Identifier
        srv_bytes = bytes(int(b) for b in server_ip.split('.'))
        response[pos] = OPTION_SERVER_ID; pos += 1
        response[pos] = 4; pos += 1
        response[pos:pos + 4] = srv_bytes; pos += 4

        response[pos] = OPTION_END
        result = bytes(response[:pos + 1])

        type_names = {2: 'OFFER', 5: 'ACK', 6: 'NAK'}
        mac = ':'.join('{:02X}'.format(b) for b in request.get('chaddr', b'\x00' * 6)[:6])
        logger.info(
            f"[DHCP 构建{type_names.get(msg_type, '?')}] "
            f"MAC={mac} xid=0x{request['xid']:08x} "
            f"yiaddr={offered_ip} siaddr={server_ip} "
            f"netmask={netmask} gateway={pool.gateway or '(none)'} "
            f"flags=0x{int(request['flags']):04x} pkt_size={len(result)}"
        )
        return result

    def _handle_client(self, data, client_addr):
        """处理客户端请求 — 外层包装：DB连接保活 + 异常兜底"""
        from django.db import connection
        try:
            connection.ensure_connection()
        except Exception as e:
            logger.warning(f"数据库连接异常，尝试重连: {e}")
            connection.close()

        try:
            self._do_handle_client(data, client_addr)
        except Exception as e:
            logger.error(f"处理DHCP请求异常: {e}", exc_info=True)

    def _do_handle_client(self, data, client_addr):
        """实际DHCP请求处理逻辑"""
        logger.info(f"[DHCP 收到] 来自 {client_addr[0]}:{client_addr[1]}, 大小={len(data)}")

        packet = self._parse_dhcp_packet(data)
        if not packet:
            logger.warning(f"[DHCP 解析失败] 来自 {client_addr[0]}")
            return

        msg_type_opt = packet['options'].get(OPTION_MESSAGE_TYPE)
        if not msg_type_opt or len(msg_type_opt) < 1:
            logger.warning(f"[DHCP] 包缺少消息类型选项")
            return

        msg_type = msg_type_opt[0]
        mac = ':'.join('{:02X}'.format(b) for b in packet['chaddr'][:6])

        type_names = {
            1: 'DISCOVER', 2: 'OFFER', 3: 'REQUEST',
            4: 'DECLINE', 5: 'ACK', 6: 'NAK',
            7: 'RELEASE', 8: 'INFORM'
        }
        type_name = type_names.get(msg_type, f'UNKNOWN({msg_type})')
        logger.info(f"[DHCP {type_name}] MAC={mac} 来自 {client_addr[0]}")

        pools = self._get_active_pools()
        if not pools:
            logger.warning(f"[DHCP] 没有启用的地址池，无法响应{type_name}")
            return

        # Server Identifier 检测
        server_ip = self._detect_server_ip(pools)
        logger.info(f"[DHCP] Server ID = {server_ip}")

        if msg_type == DHCP_DISCOVER:
            self._handle_discover(packet, mac, pools, server_ip, client_addr)

        elif msg_type == DHCP_REQUEST:
            self._handle_request(packet, mac, pools, server_ip, client_addr)

        elif msg_type == DHCP_RELEASE:
            self._handle_release(mac, client_addr)

    def _detect_server_ip(self, pools):
        """检测本机在DHCP子网上的真实IP地址"""
        import socket as s
        server_ip = None
        # 方法1：通过外网连接获取默认出口接口IP（最可靠）
        try:
            test_sock = s.socket(s.AF_INET, s.SOCK_DGRAM)
            try:
                test_sock.connect(('8.8.8.8', 80))
                candidate = test_sock.getsockname()[0]
                if candidate and candidate not in ('127.0.0.1', '0.0.0.0'):
                    server_ip = candidate
            finally:
                test_sock.close()
        except Exception:
            pass
        # 方法2：通过网关获取
        if not server_ip and pools and pools[0].gateway:
            try:
                test_sock = s.socket(s.AF_INET, s.SOCK_DGRAM)
                try:
                    test_sock.connect((pools[0].gateway, 68))
                    candidate = test_sock.getsockname()[0]
                    if candidate and candidate != '127.0.0.1':
                        server_ip = candidate
                finally:
                    test_sock.close()
            except Exception:
                pass
        # 兜底
        if not server_ip:
            server_ip = '192.168.31.61'
        return server_ip

    def _handle_discover(self, packet, mac, pools, server_ip, client_addr):
        """处理 DISCOVER 请求（支持DHCP Relay中继场景）"""
        pool = None
        giaddr = packet['giaddr']

        for p in pools:
            import ipaddress as ia
            net = ia.ip_network(p.subnet.cidr, strict=False)
            if giaddr and giaddr != '0.0.0.0':
                # ★ 中继模式：按giaddr（中继代理IP）所属子网匹配地址池
                try:
                    if ia.ip_address(giaddr) in net:
                        pool = p
                        logger.info(f"[DHCP DISCOVER] MAC={mac} 中继模式, giaddr={giaddr}, 匹配到池={p.name} ({p.subnet.cidr})")
                        break
                except Exception:
                    pass
            else:
                # 直连模式：取第一个可用池
                if pool is None:
                    pool = p

        if not pool:
            logger.warning(f"[DHCP DISCOVER] MAC={mac} 无匹配地址池 (giaddr={giaddr}, 可用池={[p.subnet.cidr for p in pools]})")
            self._write_log('discover', mac, client_addr=client_addr, status='ignored',
                           detail=f'没有匹配的地址池, giaddr={giaddr}')
            return

        # 检查历史分配是否仍有效
        with self._lock:
            existing_ip = self._allocated_ips.get(mac)

        if existing_ip and not self._is_ip_excluded_fresh(pool.id, existing_ip):
            offered_ip = existing_ip
            logger.info(f"[DHCP DISCOVER] MAC={mac} 原IP={existing_ip} 有效")
        elif existing_ip and self._is_ip_excluded_fresh(pool.id, existing_ip):
            logger.warning(f"[DHCP DISCOVER] MAC={mac} 原IP={existing_ip} 已被排除/保留")
            with self._lock:
                self._allocated_ips.pop(mac, None)
            offered_ip = self._get_available_ip(pool)
            logger.info(f"[DHCP DISCOVER] MAC={mac} 重分配新IP={offered_ip}")
        else:
            offered_ip = self._get_available_ip(pool)

        if not offered_ip:
            logger.warning(f"[DHCP DISCOVER] MAC={mac} 无可用IP")
            self._write_log('discover', mac, client_addr=client_addr, status='fail',
                           pool_name=pool.name, server_id=server_id,
                           detail=f'无可用IP')
            return

        response = self._build_dhcp_response(packet, DHCP_OFFER, offered_ip, pool, server_ip)
        self._send_response(response, client_addr, packet['flags'], packet['giaddr'])
        logger.info(f"[DHCP OFFER] MAC={mac} -> {offered_ip} ({pool.name}), giaddr={packet['giaddr']}")
        self._write_log('offer', mac, ip_addr=offered_ip, client_addr=client_addr,
                       status='success', pool_name=pool.name, server_id=server_ip)

    def _handle_request(self, packet, mac, pools, server_ip, client_addr):
        """★ 处理 REQUEST（续约/新请求）— 完整try保护确保不超时"""
        offered_ip = None
        pool = None
        requested_ip = ''

        try:
            # 1) 内存中的历史分配
            with self._lock:
                existing_alloc = self._allocated_ips.get(mac)

            # 2) 客户端请求IP — 续约时ciaddr最可靠
            requested_ip = packet['ciaddr']
            if not requested_ip or requested_ip == '0.0.0.0':
                req_opt = packet['options'].get(50)
                if req_opt and len(req_opt) >= 4:
                    requested_ip = '.'.join(str(b) for b in req_opt[:4])

            logger.info(f"[DHCP REQUEST] MAC={mac} 已有={existing_alloc} 请求IP={requested_ip} giaddr={packet['giaddr']}")

            # 3) 三级优先级分配 + 排除检查
            if existing_alloc:
                pool = self._find_pool_for_ip(pools, existing_alloc)
                if pool and not self._is_ip_excluded_fresh(pool.id, existing_alloc):
                    offered_ip = existing_alloc
                    logger.info(f"[DHCP REQUEST] MAC={mac} 续约原IP={existing_alloc} 有效")
                else:
                    logger.warning(f"[DHCP REQUEST] MAC={mac} 原IP={existing_alloc} 已被排除/保留")
                    with self._lock:
                        self._allocated_ips.pop(mac, None)
                    if not pool:
                        pool = pools[0]
                    offered_ip = self._get_available_ip(pool)

            elif requested_ip and requested_ip != '0.0.0.0':
                pool = self._find_pool_for_ip(pools, requested_ip)
                if pool and not self._is_ip_excluded_fresh(pool.id, requested_ip):
                    offered_ip = requested_ip
                elif pool:
                    logger.warning(f"[DHCP REQUEST] 请求IP={requested_ip} 已被排除/保留")
                    offered_ip = self._get_available_ip(pool)
                else:
                    pool = pools[0]
                    offered_ip = self._get_available_ip(pool)
            else:
                pool = pools[0]
                offered_ip = self._get_available_ip(pool)

            # 最终安全校验
            if pool and offered_ip and self._is_ip_excluded_fresh(pool.id, offered_ip):
                logger.warning(f"[DHCP REQUEST] 最终校验 IP={offered_ip} 被排除，重分配")
                with self._lock:
                    self._allocated_ips.pop(mac, None)
                offered_ip = self._get_available_ip(pool)

        except Exception as e:
            logger.error(f"[DHCP REQUEST] 异常 MAC={mac}: {e}", exc_info=True)
            if not pool and pools:
                pool = pools[0]
            if pool:
                try:
                    offered_ip = self._get_available_ip(pool)
                except Exception:
                    offered_ip = None

        # ★ 发送响应（无论正常还是异常都必须发！）
        if not offered_ip or not pool:
            nak_data = self._build_nak(packet, server_ip)
            self._send_response(nak_data, client_addr, packet['flags'], packet['giaddr'])
            logger.warning(f"[DHCP NAK] MAC={mac} 无可用IP, requested={requested_ip}")
            self._write_log('nak', mac, client_addr=client_addr, status='fail',
                           server_id=server_ip, detail=f'无可用IP')
            return

        # 更新内存 + 发送ACK + 异步写DB
        with self._lock:
            self._allocated_ips[mac] = offered_ip
        response = self._build_dhcp_response(packet, DHCP_ACK, offered_ip, pool, server_ip)
        self._send_response(response, client_addr, packet['flags'], packet['giaddr'])
        self._total_served += 1
        logger.info(f"[DHCP ACK] MAC={mac} -> {offered_ip} ({pool.name}), ServerID={server_ip}, giaddr={packet['giaddr']}")
        self._record_lease_async(offered_ip, mac, pool)
        self._write_log('ack', mac, ip_addr=offered_ip, client_addr=client_addr,
                       status='success', pool_name=pool.name, server_id=server_ip,
                       detail=f'分配IP {offered_ip}')

    def _handle_release(self, mac, client_addr):
        """处理 RELEASE"""
        with self._lock:
            released = self._allocated_ips.pop(mac, None)
        if released:
            logger.info(f"[DHCP RELEASE] MAC={mac} 释放了 IP={released}")
            self._write_log('release', mac, ip_addr=released, client_addr=client_addr,
                           status='success', detail=f'释放IP {released}')
        else:
            self._write_log('release', mac, client_addr=client_addr,
                           status='ignored', detail='无内存分配记录')

    def _send_response(self, data, client_addr, flags, giaddr='0.0.0.0'):
        """发送响应 — 支持DHCP中继(Relay)场景
        中继场景(giaddr!=0)：必须将响应发回给giaddr:67，由中继代理转发给客户端
        非中继场景(giaddr=0)：广播+单播双重保障
        """
        try:
            broadcast = (int(flags) & 0x8000) != 0
            sent_count = 0

            # ★ DHCP Relay（中继）场景 — 响应必须发给中继代理的67端口！
            if giaddr and giaddr != '0.0.0.0':
                try:
                    self.server_socket.sendto(data, (giaddr, 67))
                    sent_count += 1
                    logger.info(f"[DHCP发送] 中继模式: 响应已发到 {giaddr}:67")
                except Exception as e_relay:
                    logger.warning(f"发送到中继{giaddr}:67失败: {e_relay}")
                # 兜底也广播一次
                try:
                    self.server_socket.sendto(data, ('255.255.255.255', 68))
                    sent_count += 1
                except Exception:
                    pass
            else:
                # ★ 直连场景 — 广播 + 单播
                try:
                    self.server_socket.sendto(data, ('255.255.255.255', 68))
                    sent_count += 1
                except Exception as e1:
                    logger.warning(f"广播发送失败: {e1}")
                if not broadcast:
                    try:
                        self.server_socket.sendto(data, client_addr)
                        sent_count += 1
                    except Exception as e2:
                        logger.warning(f"单播发送失败: {e2}")

            if sent_count == 0:
                logger.error("DHCP响应发送完全失败！")
            else:
                logger.debug(f"DHCP响应已发送({sent_count}次), 大小={len(data)} bytes")

        except Exception as e:
            logger.error(f"发送DHCP响应异常: {e}")

    def _record_lease(self, ip, mac, pool):
        """记录租约到数据库"""
        try:
            from .models import DHCPLease
            from django.utils import timezone
            import datetime
            now = timezone.now()
            lease_time_sec = pool.lease_time
            mac_upper = mac.upper()
            old_leases = DHCPLease.objects.filter(
                mac_address=mac_upper, status='active'
            ).exclude(ip_address=ip)
            old_count = old_leases.count()
            if old_count > 0:
                old_leases.update(status='released')
                logger.info(f"[DHCP 租约回收] MAC={mac_upper} 回收{old_count}条旧租约")
            DHCPLease.objects.update_or_create(
                ip_address=ip, mac_address=mac_upper,
                defaults={
                    'hostname': '', 'device_identifier': '',
                    'start_time': now, 'end_time': now + datetime.timedelta(seconds=lease_time_sec),
                    'status': 'active', 'pool': pool,
                }
            )
        except Exception as e:
            logger.error(f"写入租约失败: {e}")

    def _record_lease_async(self, ip, mac, pool):
        """异步记录租约"""
        def _do_write():
            try:
                self._record_lease(ip, mac, pool)
            except Exception as e:
                logger.error(f"异步写租约失败: {e}")
        t = threading.Thread(target=_do_write, daemon=True)
        t.start()

    LOG_MAX_COUNT = 5000

    def _write_log(self, msg_type, mac, ip_addr=None, client_addr='', status='success',
                   pool_name='', server_id='', detail=''):
        """异步写入日志，超5000条自动清理"""
        def _do_write():
            try:
                from .models import DHCPLog
                from django.utils import timezone
                # 注意：DHCP服务在Django进程内运行，无需调用django.setup()
                total = DHCPLog.objects.count()
                if total >= self.LOG_MAX_COUNT:
                    delete_count = total - self.LOG_MAX_COUNT + 1
                    oldest_ids = list(DHCPLog.objects.order_by('created_at')[:delete_count].values_list('id', flat=True))
                    DHCPLog.objects.filter(id__in=oldest_ids).delete()
                    logger.info(f"DHCP日志已满({total}条)，清理{delete_count}条旧记录")
                DHCPLog.objects.create(
                    msg_type=msg_type, mac_address=mac.upper(),
                    ip_address=ip_addr or None, client_addr=client_addr[0] if client_addr else '',
                    pool_name=pool_name, server_id=server_id, status=status,
                    detail=detail[:500] if detail else '', created_at=timezone.now(),
                )
            except Exception as e:
                logger.error(f"写入DHCP日志失败: {e}")
        t = threading.Thread(target=_do_write, daemon=True)
        t.start()

    def _run(self):
        """主监听循环"""
        logger.info("DHCP服务启动，监听端口 67...")
        buffer_size = 4096
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                data, addr = self.server_socket.recvfrom(buffer_size)
                if data:
                    self._handle_client(data, addr)
                consecutive_errors = 0
            except socket.timeout:
                continue
            except OSError as e:
                fatal_errors = ('Bad file descriptor', 'Address family not',
                                 'Invalid argument', 'Socket is already')
                is_fatal = any(msg in str(e) for msg in fatal_errors)
                if is_fatal:
                    logger.error(f"致命Socket错误，停止: {e}")
                    self.running = False
                    break
                consecutive_errors += 1
                if self.running:
                    logger.warning(f"Socket错误 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error("连续错误过多，重建Socket...")
                    self._rebuild_socket()
                    consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"处理异常 ({consecutive_errors}): {e}")
                if consecutive_errors > MAX_CONSECUTIVE_ERRORS * 2:
                    logger.critical("连续异常过多，停止服务")
                    break
                import time as _time
                _time.sleep(min(consecutive_errors * 0.1, 2.0))
        logger.info("DHCP服务已停止")

    def _rebuild_socket(self):
        """重建socket"""
        try:
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass
            import time as _time
            _time.sleep(1)
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.server_socket.bind(('0.0.0.0', 67))
            logger.info("DHCP Socket重建成功")
            return True
        except Exception as e:
            logger.error(f"DHCP Socket重建失败: {e}")
            self.running = False
            return False

    def start(self, bind_ip='0.0.0.0', bind_port=67):
        """启动 DHCP 服务"""
        if self.running:
            return False, "DHCP服务已在运行中"
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.server_socket.bind((bind_ip, bind_port))
            self.running = True
            self._start_time = time.time()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            pools = self._get_active_pools()
            return True, f"DHCP服务已启动，共{len(pools)}个地址池"
        except PermissionError:
            return False, "权限不足！端口67需要root权限运行 (sudo)"
        except OSError as e:
            err_msg = str(e)
            if 'Permission' in err_msg or 'Operation not permitted' in err_msg:
                return False, "权限不足！端口67需要root权限 (请用 sudo 启动服务)"
            if 'Address already in use' in err_msg:
                return False, f"端口{bind_port}已被占用，可能其他DHCP服务正在运行"
            return False, f"启动失败: {err_msg}"
        except Exception as e:
            return False, f"启动异常: {e}"

    def stop(self):
        """停止 DHCP 服务"""
        if not self.running:
            return False, "DHCP服务未在运行"
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        with self._lock:
            self._allocated_ips.clear()
        info = f"已停止，累计服务 {self._total_served} 次"
        self._start_time = None
        return True, info


# 全局单例
_dhcp_server_instance = None
_instance_lock = threading.Lock()


def get_dhcp_server():
    """获取全局DHCP服务实例"""
    global _dhcp_server_instance
    with _instance_lock:
        if _dhcp_server_instance is None:
            _dhcp_server_instance = DHCPServer()
        return _dhcp_server_instance
