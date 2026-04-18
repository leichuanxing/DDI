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

    def _get_available_ip(self, pool):
        """从地址池中获取一个可用IP（排除已分配和排除范围）"""
        import ipaddress
        start = int(ipaddress.ip_address(pool.start_address))
        end = int(ipaddress.ip_address(pool.end_address))
        
        # 收集已分配和排除的IP
        used_ips = set(self._allocated_ips.values())
        for excl in pool.exclusions.all():
            es = int(ipaddress.ip_address(excl.start_ip))
            ee = int(ipaddress.ip_address(excl.end_ip))
            for i in range(es, ee + 1):
                used_ips.add(str(ipaddress.ip_address(i)))

        # 从可用IP中随机选一个
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
            # 解析 BOOTP 头部
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
            
            # 解析 Options (从偏移236开始)
            options = {}
            pos = 236
            magic_cookie = struct.unpack('!I', data[pos:pos+4])[0]
            pos += 4
            
            if magic_cookie != 0x63825363:  # DHCP magic cookie
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
                'op': op,
                'htype': htype,
                'hlen': hlen,
                'xid': xid,
                'secs': secs,
                'flags': flags,
                'ciaddr': ciaddr,
                'yiaddr': yiaddr,
                'siaddr': siaddr,
                'giaddr': giaddr,
                'chaddr': chaddr,
                'options': options,
            }
        except Exception as e:
            logger.debug(f"解析DHCP包失败: {e}")
            return None

    def _build_dhcp_response(self, request, msg_type, offered_ip, pool, server_ip='0.0.0.0'):
        """构建 DHCP 响应包"""
        import ipaddress

        # 获取子网掩码
        network = ipaddress.ip_network(pool.subnet.cidr, strict=False)
        netmask = str(network.netmask)

        # 构建响应数据包
        response = bytearray(576)
        
        # BOOTP header
        response[0] = 2  # BOOTREPLY
        response[1] = request['htype']  # Hardware type
        response[2] = request['hlen']  # Hardware address length
        response[3] = 0  # Hops
        response[4:8] = struct.pack('!I', request['xid'])  # Transaction ID
        response[8:10] = struct.pack('!H', 0)  # Seconds
        response[10:12] = struct.pack('!H', request['flags'])  # Flags
        
        # IP addresses (client IP / your IP / server IP / gateway IP)
        # DHCPOFFER和DHCPACK都需要在yiaddr中填入分配的IP
        if offered_ip and offered_ip != '0.0.0.0':
            ip_bytes = bytes(int(b) for b in offered_ip.split('.'))
            response[16:20] = ip_bytes  # yiaddr = offered IP
        
        siaddr_bytes = bytes(int(b) for b in server_ip.split('.'))
        response[20:24] = siaddr_bytes  # siaddr
        
        if request['giaddr'] != '0.0.0.0':
            giaddr_bytes = bytes(int(b) for b in request['giaddr'].split('.'))
            response[24:28] = giaddr_bytes  # giaddr (relay agent)

        # Client hardware address
        chaddr_len = min(len(request['chaddr']), 16)
        response[28:28 + chaddr_len] = request['chaddr'][:chaddr_len]

        # Magic cookie
        pos = 236
        response[pos:pos+4] = struct.pack('!I', 0x63825363)
        pos += 4

        # Option 53: DHCP Message Type
        response[pos] = OPTION_MESSAGE_TYPE; pos += 1
        response[pos] = 1; pos += 1
        response[pos] = msg_type; pos += 1

        # Option 1: Subnet Mask
        mask_bytes = bytes(int(b) for b in netmask.split('.'))
        response[pos] = OPTION_SUBNET_MASK; pos += 1
        response[pos] = 4; pos += 1
        response[pos:pos+4] = mask_bytes; pos += 4

        # Option 3: Router/Gateway
        if pool.gateway:
            gw_bytes = bytes(int(b) for b in pool.gateway.split('.'))
            response[pos] = OPTION_ROUTERS; pos += 1
            response[pos] = 4; pos += 1
            response[pos:pos+4] = gw_bytes; pos += 4

        # Option 6: DNS Servers
        if pool.dns_servers:
            dns_list = [s.strip() for s in pool.dns_servers.split(',') if s.strip()]
            dns_bytes = b''
            for dns in dns_list[:4]:  # 最多4个DNS
                dns_bytes += bytes(int(b) for b in dns.split('.'))
            if dns_bytes:
                response[pos] = OPTION_DNS_SERVERS; pos += 1
                response[pos] = len(dns_bytes); pos += 1
                response[pos:pos+len(dns_bytes)] = dns_bytes; pos += len(dns_bytes)

        # Option 51: Lease Time
        lease_bytes = struct.pack('!I', pool.lease_time)
        response[pos] = OPTION_LEASE_TIME; pos += 1
        response[pos] = 4; pos += 1
        response[pos:pos+4] = lease_bytes; pos += 4

        # Option 54: Server Identifier
        srv_bytes = bytes(int(b) for b in server_ip.split('.'))
        response[pos] = OPTION_SERVER_ID; pos += 1
        response[pos] = 4; pos += 1
        response[pos:pos+4] = srv_bytes; pos += 4

        # End option
        response[pos] = OPTION_END

        return bytes(response[:pos+1])

    def _handle_client(self, data, client_addr):
        """处理客户端请求"""
        packet = self._parse_dhcp_packet(data)
        if not packet:
            return

        msg_type_opt = packet['options'].get(OPTION_MESSAGE_TYPE)
        if not msg_type_opt or len(msg_type_opt) < 1:
            return

        msg_type = msg_type_opt[0]
        mac = ':'.join('{:02X}'.format(b) for b in packet['chaddr'][:6])

        # 确定服务器IP（优先使用地址池的网关，否则自动检测本机IP）
        pools = self._get_active_pools()
        if pools and pools[0].gateway:
            server_ip = pools[0].gateway
        else:
            # 自动检测本机在对应子网的IP
            import socket as s
            try:
                # 尝试连接外网获取本机IP
                test_sock = s.socket(s.AF_INET, s.SOCK_DGRAM)
                test_sock.connect(('8.8.8.8', 80))
                server_ip = test_sock.getsockname()[0]
                test_sock.close()
            except:
                server_ip = '192.168.31.61'

        if msg_type == DHCP_DISCOVER:
            # 客户端发现DHCP服务器
            pool = None
            offered_ip = None

            # 尝试根据giaddr/网络匹配池
            for p in pools:
                import ipaddress as ia
                net = ia.ip_network(p.subnet.cidr, strict=False)
                # 检查是否在子网范围内
                if packet['giaddr'] != '0.0.0.0':
                    try:
                        if ia.ip_address(packet['giaddr']) in net:
                            pool = p
                            break
                    except:
                        pass
                else:
                    # 使用第一个可用的池
                    if pool is None:
                        pool = p

            if pool:
                # 先检查是否已有分配记录
                with self._lock:
                    existing_ip = self._allocated_ips.get(mac)
                
                if existing_ip:
                    offered_ip = existing_ip
                else:
                    offered_ip = self._get_available_ip(pool)

            if offered_ip and pool:
                response = self._build_dhcp_response(packet, DHCP_OFFER, offered_ip, pool, server_ip)
                self._send_response(response, client_addr, packet['flags'])
                logger.info(f"[DHCP OFFER] MAC={mac} -> IP={offered_ip} ({pool.name})")

        elif msg_type == DHCP_REQUEST:
            # 客户端请求IP
            requested_ip = packet.get('yiaddr', '') or packet.get('ciaddr', '')
            
            # 如果没有requested_ip，尝试从选项中获取
            if not requested_ip or requested_ip == '0.0.0.0':
                req_opt = packet['options'].get(50)  # Requested IP Address option
                if req_opt and len(req_opt) >= 4:
                    requested_ip = '.'.join(str(b) for b in req_opt[:4])

            # 找到对应的pool
            pool = None
            if requested_ip and requested_ip != '0.0.0.0':
                for p in pools:
                    import ipaddress as ia
                    try:
                        net = ia.ip_network(p.subnet.cidr, strict=False)
                        start = int(ia.ip_address(p.start_address))
                        end = int(ia.ip_address(p.end_address))
                        req_int = int(ia.ip_address(requested_ip))
                        if ia.ip_address(requested_ip) in net and start <= req_int <= end:
                            pool = p
                            break
                    except:
                        pass

            if not pool:
                pool = pools[0] if pools else None
                if pool:
                    offered_ip = self._get_available_ip(pool)
                else:
                    offered_ip = None
            else:
                offered_ip = requested_ip

            if offered_ip and pool:
                # 记录分配
                with self._lock:
                    self._allocated_ips[mac] = offered_ip
                
                # 写入租约数据库
                self._record_lease(offered_ip, mac, pool)

                response = self._build_dhcp_response(packet, DHCP_ACK, offered_ip, pool, server_ip)
                self._send_response(response, client_addr, packet['flags'])
                self._total_served += 1
                logger.info(f"[DHCP ACK] MAC={mac} -> IP={offered_ip} ({pool.name})")
            else:
                # 发送NAK
                nak_data = bytearray(576)
                nak_data[0] = 2
                nak_data[4:8] = struct.pack('!I', packet['xid'])
                nak_data[28:34] = packet['chaddr'][:6]
                pos = 236
                nak_data[pos:pos+4] = struct.pack('!I', 0x63825363); pos += 4
                nak_data[pos] = 53; pos += 1; nak_data[pos] = 1; pos += 1; nak_data[pos] = DHCP_NAK; pos += 1
                nak_data[pos] = 54; pos += 1; nak_data[pos] = 4; pos += 1
                srv_b = bytes(int(b) for b in server_ip.split('.'))
                nak_data[pos:pos+4] = srv_b; pos += 4
                nak_data[pos] = 255
                self._send_response(bytes(nak_data), client_addr, packet['flags'])
                logger.warning(f"[DHCP NAK] MAC={mac} 无可用IP")

        elif msg_type == DHCP_RELEASE:
            # 客户端释放IP
            with self._lock:
                released = self._allocated_ips.pop(mac, None)
            if released:
                logger.info(f"[DHCP RELEASE] MAC={mac} 释放了 IP={released}")

    def _send_response(self, data, client_addr, flags):
        """发送响应（广播或单播）"""
        try:
            # flags已经是整数，直接检查广播标志位
            broadcast = (int(flags) & 0x8000) != 0
            if broadcast:
                self.server_socket.sendto(data, ('255.255.255.255', 68))
            else:
                self.server_socket.sendto(data, client_addr)
        except Exception as e:
            logger.error(f"发送DHCP响应失败: {e}")

    def _record_lease(self, ip, mac, pool):
        """记录租约到数据库"""
        try:
            from .models import DHCPLease
            from django.utils import timezone
            import datetime

            now = timezone.now()
            lease_time_sec = pool.lease_time

            DHCPLease.objects.update_or_create(
                ip_address=ip,
                mac_address=mac.upper(),
                defaults={
                    'hostname': '',
                    'device_identifier': '',
                    'start_time': now,
                    'end_time': now + datetime.timedelta(seconds=lease_time_sec),
                    'status': 'active',
                    'pool': pool,
                }
            )
        except Exception as e:
            logger.error(f"写入租约失败: {e}")

    def _run(self):
        """主监听循环"""
        logger.info("DHCP服务启动，监听端口 67...")
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
                logger.error(f"处理请求异常: {e}")

        logger.info("DHCP服务已停止")

    def start(self, bind_ip='0.0.0.0', bind_port=67):
        """启动 DHCP 服务"""
        if self.running:
            return False, "DHCP服务已在运行中"

        try:
            # 创建 UDP socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # 绑定到端口67 (需要root权限或CAP_NET_BIND_SERVICE)
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
            except:
                pass
            self.server_socket = None

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

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
