"""
IPAM 探测核心引擎
支持 Ping 探测、端口扫描、ARP 扫描
使用 Python 标准库和第三方库实现
"""

import subprocess
import socket
import threading
import time
import concurrent.futures
import re
import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class PingResult:
    """Ping探测结果"""
    ip: str
    success: bool = False
    packet_sent: int = 0
    packet_received: int = 0
    packet_loss: float = 100.0
    min_time: float = 0.0
    max_time: float = 0.0
    avg_time: float = 0.0
    ttl: Optional[int] = None
    error: str = ""


@dataclass
class PortResult:
    """端口扫描结果"""
    port: int
    state: str  # open, closed, filtered
    service: str = ""
    banner: str = ""


@dataclass
class ScanHostResult:
    """单主机综合扫描结果"""
    ip: str
    is_online: bool = False
    ping: Optional[PingResult] = None
    ports: Dict[int, PortResult] = field(default_factory=dict)
    mac_address: str = ""
    vendor: str = ""
    reverse_dns: str = ""


class PingScanner:
    """Ping 探测器 - 支持跨平台"""
    
    def __init__(self, count: int = 3, timeout: float = 1.0):
        self.count = count
        self.timeout = timeout
    
    def ping(self, ip: str) -> PingResult:
        """对单个IP执行Ping检测"""
        result = PingResult(ip=ip)
        
        # 根据操作系统选择命令
        import platform
        system = platform.system().lower()
        
        try:
            if system == 'windows':
                cmd = ['ping', '-n', str(self.count), '-w', str(int(self.timeout * 1000)), ip]
            else:
                cmd = ['ping', '-c', str(self.count), '-W', str(self.timeout), ip]
            
            proc = subprocess.run(cmd, capture_output=True, text=True, 
                                  timeout=self.timeout * self.count + 5)
            output = proc.stdout + proc.stderr
            
            result = self._parse_output(ip, output, system)
            
        except subprocess.TimeoutExpired:
            result.error = "超时"
        except FileNotFoundError:
            result.error = "ping命令未找到"
        except Exception as e:
            result.error = str(e)
        
        return result
    
    def _parse_output(self, ip: str, output: str, os_type: str) -> PingResult:
        """解析ping输出"""
        result = PingResult(ip=ip)
        
        if 'windows' in os_type:
            # Windows 格式解析
            loss_match = re.search(r'\((\d+)%\s*loss\)', output)
            if loss_match:
                result.packet_loss = float(loss_match.group(1))
            
            times = re.findall(r'时间[=<](\d+)ms|time[=<](\d+)ms|(\d+)ms.*TTL', output, re.IGNORECASE)
            if times:
                ms_values = []
                for t in times:
                    val = t[0] or t[1] or t[2]
                    if val:
                        ms_values.append(float(val))
                if ms_values:
                    result.min_time = min(ms_values)
                    result.max_time = max(ms_values)
                    result.avg_time = sum(ms_values) / len(ms_values)
            
            ttl_match = re.search(r'TTL[=(\s]*(\d+)', output, re.IGNORECASE)
            if ttl_match:
                result.ttl = int(ttl_match.group(1))
                
            result.packet_sent = self.count
            received_match = re.search(r'已接收\s*=\s*(\d+)|Received\s*=\s*(\d+)', output, re.IGNORECASE)
            if received_match:
                result.packet_received = int(received_match.group(1) or received_match.group(2))
            
        else:
            # Linux/Mac 格式解析
            loss_match = re.search(r'(\d+(?:\.\d+)?)%\s*packet\s*loss', output)
            if loss_match:
                result.packet_loss = float(loss_match.group(1))
            
            # rtt min/avg/max/mdev
            rtt_match = re.search(
                r'rtt\s+min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)',
                output
            )
            if rtt_match:
                result.min_time = float(rtt_match.group(1))
                result.avg_time = float(rtt_match.group(2))
                result.max_time = float(rtt_match.group(3))
            
            ttl_match = re.search(r'ttl=(\d+)', output, re.IGNORECASE)
            if ttl_match:
                result.ttl = int(ttl_match.group(1))
            
            # 发送/接收统计
            stats_match = re.search(r'(\d+)\s*packets\s*transmitted,\s*(\d+)\s*(?:packets\s*)?received', output)
            if stats_match:
                result.packet_sent = int(stats_match.group(1))
                result.packet_received = int(stats_match.group(2))
        
        result.success = result.packet_received > 0 and result.packet_loss < 100
        return result
    
    def ping_batch(self, ips: List[str], max_workers: int = 50) -> Dict[str, PingResult]:
        """批量Ping检测"""
        results = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ip = {executor.submit(self.ping, ip): ip for ip in ips}
            for future in concurrent.futures.as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    results[ip] = future.result()
                except Exception as e:
                    results[ip] = PingResult(ip=ip, error=str(e))
        
        return results


class PortScanner:
    """TCP 端口扫描器"""
    
    # 常见服务端口映射
    COMMON_SERVICES = {
        21: 'ftp', 22: 'ssh', 23: 'telnet', 25: 'smtp',
        53: 'dns', 67: 'dhcp', 68: 'dhcp', 69: 'tftp',
        80: 'http', 110: 'pop3', 111: 'rpcbind', 135: 'msrpc',
        137: 'netbios-ns', 138: 'netbios-dgm', 139: 'netbios-ssn',
        143: 'imap', 161: 'snmp', 162: 'snmptrap', 389: 'ldap',
        443: 'https', 445: 'microsoft-ds', 993: 'imaps', 995: 'pop3s',
        1433: 'mssql', 1521: 'oracle', 3306: 'mysql', 3389: 'rdp',
        5432: 'postgresql', 5900: 'vnc', 6379: 'redis', 8080: 'http-proxy',
        8443: 'https-alt', 8888: 'http-alt', 9090: 'http-alt',
        27017: 'mongodb'
    }
    
    def __init__(self, timeout: float = 2.0):
        self.timeout = timeout
    
    def scan_port(self, ip: str, port: int) -> PortResult:
        """扫描单个端口"""
        result = PortResult(port=port, state='closed')
        result.service = self.COMMON_SERVICES.get(port, '')
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            connection_result = sock.connect_ex((ip, port))
            
            if connection_result == 0:
                result.state = 'open'
                # 尝试获取Banner
                try:
                    sock.sendall(b'\r\n')
                    banner = sock.recv(1024).decode('utf-8', errors='ignore').strip()
                    if banner:
                        result.banner = banner[:200]  # 限制长度
                except:
                    pass
            
            sock.close()
        except socket.timeout:
            result.state = 'filtered'
        except Exception as e:
            result.state = 'error'
        
        return result
    
    def scan_host(self, ip: str, ports: List[int], max_workers: int = 100) -> Dict[int, PortResult]:
        """扫描单个主机的多个端口"""
        results = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_port = {executor.submit(self.scan_port, ip, port): port for port in ports}
            for future in concurrent.futures.as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    results[port] = future.result()
                except Exception:
                    results[port] = PortResult(port=port, state='error')
        
        return results
    
    @staticmethod
    def parse_ports(port_string: str) -> List[int]:
        """解析端口字符串，支持逗号分隔和范围表示"""
        ports = set()
        parts = port_string.split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                try:
                    start, end = part.split('-', 1)
                    start, end = int(start.strip()), int(end.strip())
                    if 1 <= start <= 65535 and 1 <= end <= 65535:
                        ports.update(range(min(start, end), max(start, end) + 1))
                except ValueError:
                    continue
            else:
                try:
                    port = int(part)
                    if 1 <= port <= 65535:
                        ports.add(port)
                except ValueError:
                    continue
        
        return sorted(list(ports))


class ARPScanner:
    """ARP 扫描器 - 获取本地网络MAC地址"""
    
    @staticmethod
    def get_arp_table() -> Dict[str, str]:
        """获取系统ARP表"""
        arp_table = {}
        
        try:
            import platform
            system = platform.system().lower()
            
            if system == 'windows':
                proc = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=10)
                for line in proc.stdout.splitlines():
                    match = re.match(r'(\S+)\s+([0-9a-fA-F:-]{17})', line.strip())
                    if match:
                        ip, mac = match.groups()
                        arp_table[ip] = mac.upper().replace('-', ':')
            else:
                # Linux/Mac
                proc = subprocess.run(['arp', '-n'], capture_output=True, text=True, timeout=10)
                for line in proc.stdout.splitlines():
                    # Linux格式: 192.168.1.1    ether   aa:bb:cc:dd:ee:ff
                    # Mac格式: ? (192.168.1.1) at aa:bb:cc:dd:ee:ff
                    match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+[^\s]*\s+([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})', line)
                    if match:
                        ip, mac = match.groups()
                        arp_table[ip] = mac.upper()
                        
        except Exception as e:
            print(f"获取ARP表失败: {e}")
        
        return arp_table
    
    @staticmethod
    def get_mac_vendor(mac_address: str) -> str:
        """根据MAC地址前缀查询厂商（简化版，仅返回常见厂商）"""
        if not mac_address or len(mac_address) < 8:
            return ''
        
        prefix = mac_address[:8].upper()
        
        # 常见厂商OUI前缀
        vendors = {
            '00:50:56': 'VMware',
            '00:0C:29': 'VMware',
            '00:05:69': 'VMware',
            '00:16:3E': 'Oracle VM',
            '52:54:00': 'QEMU/KVM',
            '08:00:27': 'VirtualBox',
            '00:1B:21': 'Xensource',
            'DC:A9:04': 'Docker',
            '02:42:AC': 'Docker',
            '00:15:5D': 'Hyper-V',
            '00:03:FF': 'Microsoft',
            '00:1A:11': 'Cisco',
            '00:23:AC': 'Cisco',
            '00:25:B3': 'Cisco',
            '00:26:CB': 'Cisco',
            '84:2B:2B': 'Cisco',
            'F0:BF:97': 'Cisco',
            '34:E7:D4': 'Huawei',
            '00:E0:FC': 'Huawei',
            'CC:B2:55': 'H3C',
            '00:09:0F': 'H3C',
            '00:1E:E5': 'Juniper',
            '00:19:06': 'Juniper',
            '00:21:59': 'Juniper',
            '00:04:96': 'Dell',
            '84:8F:69': 'Dell',
            '18:03:73': 'HP',
            '00:26:BB': 'HP',
            '3C:D9:2E': 'HP',
            '00:14:22': 'IBM/Lenovo',
            '88:99:BB': 'Lenovo',
            'E0:94:67': 'Lenovo',
            '00:1C:B3': 'Intel',
            '00:21:CC': 'Intel',
            '00:24:D7': 'Arista',
            '90:B1:1C': 'Arista',
            '00:07:43': 'Brocade',
            '00:60:9F': 'Fortinet',
            '00:09:5B': 'Palo Alto',
            '00:01:E8': 'SonicWALL',
            '00:12:43': 'Check Point',
            '00:1D:A8': 'Check Point',
            '00:02:B3': 'D-Link',
            '00:13:46': 'TP-Link',
            'E4:95:6E': 'TP-Link',
            '80:89:17': 'TP-Link',
            '00:0C:43': 'Netgear',
            '30:85:A9': 'Netgear',
            '00:0E:C6': 'Asus',
            '8C:34:BD': 'Asus',
            '00:17:F2': 'Apple',
            '58:20:59': 'Apple',
            '40:65:A4': 'Apple',
            'EC:35:18': 'Samsung',
            'DC:71:D6': 'Xiaomi',
            '64:16:7D': 'ZTE',
            '74:91:1A': 'ZTE',
            '00:08:02': 'Qualcomm/Atheros',
        }
        
        # 尝试完整匹配前缀
        for oui, vendor in vendors.items():
            if mac_address.upper().startswith(oui):
                return vendor
        
        return ''


class DNSScanner:
    """DNS 反向解析器"""
    
    def __init__(self, timeout: float = 2.0):
        self.timeout = timeout
    
    def reverse_lookup(self, ip: str) -> str:
        """反向DNS查找"""
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except socket.herror:
            return ""
        except socket.gaierror:
            return ""
        except Exception:
            return ""
    
    def reverse_batch(self, ips: List[str], max_workers: int = 30) -> Dict[str, str]:
        """批量反向DNS查找"""
        results = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ip = {executor.submit(self.reverse_lookup, ip): ip for ip in ips}
            for future in concurrent.futures.as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    hostname = future.result()
                    if hostname:
                        results[ip] = hostname
                except Exception:
                    pass
        
        return results


class NetworkScanner:
    """综合网络扫描器 - 整合所有探测能力"""
    
    def __init__(self, ping_count: int = 3, ping_timeout: float = 1.0,
                 port_timeout: float = 2.0):
        self.ping_scanner = PingScanner(count=ping_count, timeout=ping_timeout)
        self.port_scanner = PortScanner(timeout=port_timeout)
        self.arp_scanner = ARPScanner()
        self.dns_scanner = DNSScanner()
    
    def quick_scan(self, ip: str) -> ScanHostResult:
        """快速扫描 - 仅Ping"""
        result = ScanHostResult(ip=ip)
        
        # Ping检测
        ping_result = self.ping_scanner.ping(ip)
        result.ping = ping_result
        result.is_online = ping_result.success
        
        if result.is_online:
            # DNS反解
            result.reverse_dns = self.dns_scanner.reverse_lookup(ip)
        
        return result
    
    def full_scan(self, ip: str, ports: List[int] = None) -> ScanHostResult:
        """完整扫描 - Ping + DNS + 端口 + ARP"""
        result = self.quick_scan(ip)
        
        if result.is_online:
            # 端口扫描
            if ports:
                port_results = self.port_scanner.scan_host(ip, ports)
                result.ports = port_results
            
            # 查找ARP表中的MAC
            arp_table = self.arp_scanner.get_arp_table()
            if ip in arp_table:
                result.mac_address = arp_table[ip]
                result.vendor = self.arp_scanner.get_mac_vendor(result.mac_address)
        
        return result
    
    def subnet_scan(self, ips: List[str], task_type: str = 'ping',
                    ports: List[int] = None, callback=None,
                    max_ping_workers: int = 50,
                    max_port_workers: int = 100) -> List[ScanHostResult]:
        """
        子网扫描
        :param ips: IP列表
        :param task_type: 任务类型 ping/port/full
        :param ports: 要扫描的端口列表
        :param callback: 进度回调函数 (current, total)
        :return: 扫描结果列表
        """
        results = []
        total = len(ips)
        
        # 第一阶段：Ping检测
        if task_type in ('ping', 'port', 'full', 'arp'):
            online_ips = []
            
            ping_results = self.ping_scanner.ping_batch(ips, max_workers=max_ping_workers)
            
            for i, ip in enumerate(ips):
                ping_result = ping_results.get(ip, PingResult(ip=ip))
                host_result = ScanHostResult(ip=ip)
                host_result.ping = ping_result
                host_result.is_online = ping_result.success
                
                if callback:
                    callback(i + 1, total, f"Ping: {ip}")
                
                if ping_result.success:
                    online_ips.append(ip)
                    
                    # DNS反解
                    if task_type in ('full',):
                        host_result.reverse_dns = self.dns_scanner.reverse_lookup(ip)
                
                results.append(host_result)
            
            # 第二阶段：对在线主机进行端口扫描
            if task_type in ('port', 'full') and ports and online_ips:
                for i, host in enumerate(results):
                    if host.is_online:
                        if callback:
                            callback(total + i + 1, total + len(online_ips),
                                    f"Port: {host.ip}")
                        
                        port_results = self.port_scanner.scan_host(host.ip, ports,
                                                                  max_workers=max_port_workers)
                        host.ports = port_results
            
            # 第三阶段：获取ARP信息
            if task_type in ('arp', 'full'):
                arp_table = self.arp_scanner.get_arp_table()
                for host in results:
                    if host.ip in arp_table:
                        host.mac_address = arp_table[host.ip]
                        host.vendor = self.arp_scanner.get_mac_vendor(host.mac_address)
        
        return results
