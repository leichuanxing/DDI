import ipaddress
from typing import List, Tuple


def validate_cidr(cidr: str) -> bool:
    """验证CIDR格式是否合法"""
    try:
        ipaddress.ip_network(cidr, strict=True)
        return True
    except ValueError:
        return False


def get_network_info(cidr: str) -> dict:
    """获取网络信息"""
    network = ipaddress.ip_network(cidr, strict=False)
    return {
        'network_address': str(network.network_address),
        'broadcast_address': str(network.broadcast_address),
        'netmask': str(network.netmask),
        'prefixlen': network.prefixlen,
        'num_addresses': network.num_addresses,
        'usable_range': (
            str(network.network_address + 1),
            str(network.broadcast_address - 1)
        ),
        'is_private': network.is_private,
    }


def get_ip_list_from_subnet(subnet: str) -> List[str]:
    """从子网获取所有IP地址列表"""
    network = ipaddress.ip_network(subnet, strict=False)
    return [str(ip) for ip in network.hosts()]


def ip_in_network(ip: str, network: str) -> bool:
    """判断IP是否在指定网络中"""
    try:
        ip_addr = ipaddress.ip_address(ip)
        net = ipaddress.ip_network(network, strict=False)
        return ip_addr in net
    except ValueError:
        return False


def is_valid_ip(ip: str) -> bool:
    """验证IP地址格式"""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def calculate_usage_stats(allocated_count: int, total_count: int) -> dict:
    """计算使用率统计"""
    if total_count == 0:
        return {'usage_rate': 0, 'available': 0, 'allocated': 0}
    
    usage_rate = round((allocated_count / total_count) * 100, 2)
    
    return {
        'usage_rate': usage_rate,
        'available': total_count - allocated_count,
        'allocated': allocated_count,
        'total': total_count,
    }


def generate_ptr_record(ip: str, reverse_zone: str = '') -> str:
    """根据IP生成PTR记录"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.version == 4:
            parts = str(ip_obj).split('.')
            parts.reverse()
            return '.'.join(parts) + '.in-addr.arpa.'
        else:
            # IPv6 PTR (简化处理)
            return ipaddress.ip_address(ip).reverse_pointer
    except ValueError:
        return ''
