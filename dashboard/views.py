"""
仪表盘模块 - 首页汇总展示视图
聚合IPAM/DNS/DHCP/设备/审计等模块的统计数据，并检测告警信息
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from ipam.models import Region, Subnet, IPAddress
from devices.models import Device
from logs.models import OperationLog


@login_required
def index(request):
    """首页仪表盘 - 展示全局统计、子网使用率图表、VLAN分布、DNS记录分布、告警信息"""
    
    # ========== 基础统计 ==========
    stats = {
        # IPAM 统计 - 区域数/子网数/IP总数/各状态IP数
        'region_count': Region.objects.count(),
        'subnet_count': Subnet.objects.count(),
        'ip_total': IPAddress.objects.count(),
        'ip_allocated': IPAddress.objects.filter(status='allocated').count(),  # 已分配
        'ip_available': IPAddress.objects.filter(status='available').count(),  # 空闲
        'ip_reserved': IPAddress.objects.filter(status='reserved').count(),    # 保留
        'ip_conflict': IPAddress.objects.filter(status='conflict').count(),    # 冲突
        
        
        # 设备统计
        'device_count': Device.objects.count(),
    }
    
    # 计算IP使用率（已分配/总数）
    if stats['ip_total'] > 0:
        stats['ip_usage_percent'] = round((stats['ip_allocated'] / stats['ip_total']) * 100, 1)
    else:
        stats['ip_usage_percent'] = 0
    
    # ========== 子网使用情况（用于图表，最多展示前10个子网）==========
    subnet_stats = []
    for subnet in Subnet.objects.all()[:10]:
        total_ips = subnet.total_ips if hasattr(subnet, 'total_ips') else 0
        allocated = subnet.ip_addresses.filter(status='allocated').count()
        available = total_ips - allocated
        
        subnet_stats.append({
            'name': subnet.name,
            'cidr': subnet.cidr,
            'total': total_ips,
            'allocated': allocated,
            'available': max(0, available),
            'usage_rate': round((allocated / total_ips) * 100, 1) if total_ips > 0 else 0,
        })
    
    # ========== 各VLAN地址分布（用于图表，最多展示8个VLAN）==========
    vlan_data = []
    vlans_with_subnets = Subnet.objects.values('vlan__vlan_id', 'vlan__name').annotate(
        ip_count=Count('ip_addresses')
    ).exclude(vlan__vlan_id=None)[:8]
    
    for item in vlans_with_subnets:
        vlan_data.append({
            'vlan_id': item['vlan__vlan_id'],
            'vlan_name': item['vlan__name'] or f'VLAN{item["vlan__vlan_id"]}',
            'count': item['ip_count'],
        })
    
    # ========== 最近操作记录（最多展示15条）==========
    recent_logs = OperationLog.objects.select_related('user')[:15]
    
    # ========== 告警信息（高使用率子网、IP冲突）==========
    alerts = []
    
    # 检测高使用率子网（>80%警告，>90%危险）
    for subnet in Subnet.objects.all():
        if hasattr(subnet, 'usage_percent') and subnet.usage_percent > 80:
            alerts.append({
                'level': 'danger' if subnet.usage_percent > 90 else 'warning',
                'message': f'子网 {subnet.cidr} 使用率已达 {subnet.usage_percent}%',
                'type': 'subnet_usage'
            })
    
    # 检测冲突IP（存在冲突IP时发出危险告警）
    conflict_count = stats.get('ip_conflict', 0)
    if conflict_count > 0:
        alerts.append({
            'level': 'danger',
            'message': f'存在 {conflict_count} 个冲突IP地址',
            'type': 'ip_conflict'
        })
    
    context = {
        'stats': stats,
        'subnet_stats': subnet_stats,
        'vlan_data': vlan_data,
        'recent_logs': recent_logs,
        # 最多展示5条告警
        'alerts': alerts[:5],
    }
    
    return render(request, 'dashboard/index.html', context)
