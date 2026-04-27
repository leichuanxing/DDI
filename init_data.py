#!/usr/bin/env python
"""
DDI管理系统初始化脚本
用于创建初始角色、管理员账户、DNS配置和示例数据

用法:
    python init_data.py           # 全量初始化(含示例数据)
    python init_data.py --minimal  # 仅创建角色+管理员+基础DNS配置
"""

import os
import sys
import django

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ddi_system.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from accounts.models import User, Role
from ipam.models import Region, VLAN, Subnet, IPAddress
from ipam.scan_models import SwitchDevice
from devices.models import Device


# ==================== 1. 系统角色 ====================

def create_roles():
    """创建系统角色"""
    roles_data = [
        {'name': '系统管理员', 'code': 'admin', 'description': '系统最高权限，负责用户管理、系统配置'},
        {'name': '网络管理员', 'code': 'network_admin', 'description': '管理子网、VLAN、IP地址等网络资源'},
        {'name': '运维人员', 'code': 'operator', 'description': '查询资源、申请/分配/释放IP、维护主机信息'},
        {'name': '审计用户', 'code': 'auditor', 'description': '只读权限，可查看资源和变更记录'},
    ]

    for role_data in roles_data:
        role, created = Role.objects.get_or_create(
            code=role_data['code'],
            defaults=role_data
        )
        if created:
            print(f"✓ 创建角色: {role.name}")
        else:
            print(f"  角色已存在: {role.name}")


# ==================== 2. 管理员账户 ====================

def create_admin_user():
    """创建管理员账户"""
    admin_role = Role.objects.get(code='admin')

    try:
        user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='Admin@123',
            real_name='系统管理员',
            phone='13800138000',
            department='IT部',
            role=admin_role,
        )
        print("✓ 管理员账户创建成功: admin / Admin@123")
    except Exception as e:
        print(f"  管理员已存在或创建失败: {e}")


# ==================== 3. IPAM 示例区域 ====================

def create_sample_regions():
    """创建示例区域"""
    regions = [
        {'name': '总部机房', 'code': 'HQ', 'description': '公司总部数据中心机房'},
        {'name': '研发中心', 'code': 'R&D', 'description': '研发部门所在区域'},
        {'name': '办公区A栋', 'code': 'OFFICE-A', 'description': 'A栋办公楼'},
        {'name': '办公区B栋', 'code': 'OFFICE-B', 'description': 'B栋办公楼'},
    ]

    for r in regions:
        obj, created = Region.objects.get_or_create(code=r['code'], defaults=r)
        if created:
            print(f"  ✓ 创建区域: {obj.name}")


# ==================== 4. IPAM 示例VLAN和子网 ====================

def sample_vlans():
    """创建示例VLAN"""
    vlans = [
        {'vlan_id': 10, 'name': '办公网VLAN10', 'region_code': 'HQ', 'purpose': '员工办公网络'},
        {'vlan_id': 20, 'name': '服务器网VLAN20', 'region_code': 'HQ', 'purpose': '服务器群组'},
        {'vlan_id': 30, 'name': '管理网VLAN30', 'region_code': 'HQ', 'purpose': '设备管理网络'},
        {'vlan_id': 40, 'name': '监控网VLAN40', 'region_code': 'HQ', 'purpose': '监控系统专用'},
        {'vlan_id': 50, 'name': '访客网VLAN50', 'region_code': 'OFFICE-A', 'purpose': '访客WiFi接入'},
    ]

    regions_map = {r.code: r for r in Region.objects.all()}

    for v in vlans:
        region = regions_map.get(v.pop('region_code'))
        obj, created = VLAN.objects.get_or_create(
            vlan_id=v['vlan_id'],
            defaults={**v, 'region': region}
        )
        if created:
            print(f"  ✓ 创建VLAN: VLAN{obj.vlan_id} - {obj.name}")


def sample_subnets():
    """创建示例子网"""
    subnets = [
        {
            'name': '办公子网-A区',
            'cidr': '192.168.10.0/24',
            'gateway': '192.168.10.1',
            'purpose': 'office',
            'vlan_id': 10,
            'region_code': 'HQ',
        },
        {
            'name': '服务器子网-生产',
            'cidr': '192.168.100.0/24',
            'gateway': '192.168.100.1',
            'purpose': 'server',
            'vlan_id': 20,
            'region_code': 'HQ',
        },
        {
            'name': 'DMZ区域',
            'cidr': '172.16.0.0/24',
            'gateway': '172.16.0.1',
            'purpose': 'dmz',
            'vlan_id': 30,
            'region_code': 'HQ',
        },
        {
            'name': '管理网络',
            'cidr': '192.168.31.0/24',
            'gateway': '192.168.31.1',
            'purpose': 'management',
            'vlan_id': 30,
            'region_code': 'HQ',
        },
        {
            'name': '访客网络',
            'cidr': '10.0.50.0/24',
            'gateway': '10.0.50.1',
            'purpose': 'guest',
            'vlan_id': 50,
            'region_code': 'OFFICE-A',
        },
    ]

    regions_map = {r.code: r for r in Region.objects.all()}
    vlans_map = {v.vlan_id: v for v in VLAN.objects.all()}

    for s in subnets:
        region = regions_map.get(s.pop('region_code'))
        vlan = vlans_map.get(s.pop('vlan_id'))

        subnet_obj, created = Subnet.objects.get_or_create(
            cidr=s['cidr'],
            defaults={
                **s,
                'region': region,
                'vlan': vlan,
                'prefix_len': int(s['cidr'].split('/')[1])
            }
        )

        if created:
            # 自动生成IP池
            from common.ip_utils import get_ip_list_from_subnet
            ip_list = get_ip_list_from_subnet(subnet_obj.cidr)
            ip_objects = []
            for ip in ip_list:
                status = 'reserved' if ip == subnet_obj.gateway else 'available'
                ip_objects.append(IPAddress(
                    ip_address=ip,
                    subnet=subnet_obj,
                    status=status,
                ))
            if ip_objects:
                IPAddress.objects.bulk_create(ip_objects)

            total = len(ip_objects)
            print(f"  ✓ 创建子网: {subnet_obj.name} ({subnet_obj.cidr}) - 共{total}个IP")


# ==================== 5. 设备和交换机 ====================

def sample_switch_devices():
    """创建示例交换机设备数据"""
    # 优先使用管理网络，否则取第一个可用子网
    mgmt_subnet = Subnet.objects.filter(cidr='192.168.31.0/24').first()
    if not mgmt_subnet:
        mgmt_subnet = Subnet.objects.first()

    switches = [
        {
            'name': 'config',
            'vendor': 'huawei',
            'ip_address': '192.168.31.2',
            'port': 22,
            'username': 'admin',
            'password': 'Cisco1234!',
            'enable_password': '',
            'subnet': mgmt_subnet,
            'is_active': True,
        },
    ]

    for sw in switches:
        obj, created = SwitchDevice.objects.get_or_create(
            name=sw['name'],
            defaults=sw
        )
        if created:
            print(f"  ✓ 创建交换机设备: {obj.name} ({obj.vendor}) - {obj.ip_address}")


def sample_devices():
    """创建示例设备数据"""
    devices = [
        {'hostname': 'srv-web-01', 'device_name': 'Web服务器01', 'device_type': 'server',
         'manager': '张三', 'department': 'IT部', 'mac_address': 'AA:BB:CC:11:22:33',
         'operating_system': 'CentOS 7.9', 'description': '主站Web服务器'},
        {'hostname': 'srv-db-01', 'device_name': '数据库服务器01', 'device_type': 'server',
         'manager': '李四', 'department': 'IT部', 'mac_address': 'AA:BB:CC:11:22:34',
         'operating_system': 'Ubuntu 22.04 LTS'},
        {'hostname': 'sw-core-01', 'device_name': '核心交换机', 'device_type': 'switch',
         'manager': '王五', 'department': '网络组', 'mac_address': 'AA:BB:CC:55:66:77',
         'operating_system': 'Cisco IOS XE'},
        {'hostname': 'fw-edge-01', 'device_name': '边界防火墙', 'device_type': 'firewall',
         'manager': '王五', 'department': '安全组', 'mac_address': 'AA:BB:CC:88:99:00',
         'operating_system': 'FortiOS 7.0'},
        {'hostname': 'pc-zhangsan', 'device_name': '张三的电脑', 'device_type': 'pc',
         'manager': '张三', 'department': '研发部', 'mac_address': 'AA:BB:CC:DD:EE:01',
         'operating_system': 'Windows 11'},
        # DNS服务器
        {'hostname': 'ns-devnets-01', 'device_name': 'DNS主服务器', 'device_type': 'server',
         'manager': '王五', 'department': '网络组', 'mac_address': 'AA:BB:CC:DD:EE:02',
         'operating_system': 'CentOS 8 Stream + BIND9', 'description': 'BIND9 主DNS服务器'},
    ]

    region = Region.objects.first()

    for d in devices:
        obj, created = Device.objects.get_or_create(
            hostname=d['hostname'],
            defaults={**d, 'region': region}
        )
        if created:
            # 关联IP (仅对服务器类型尝试)
            if d['device_type'] == 'server':
                try:
                    ip_obj = IPAddress.objects.filter(
                        subnet__cidr='192.168.100.0/24',
                        status='available'
                    ).first()
                    if not ip_obj:
                        ip_obj = IPAddress.objects.filter(
                            subnet__cidr='192.168.31.0/24',
                            status='available'
                        ).first()
                    if ip_obj:
                        obj.ip_address = ip_obj
                        ip_obj.status = 'allocated'
                        ip_obj.hostname = d['hostname']
                        ip_obj.device_name = d['device_name']
                        ip_obj.owner = d['manager']
                        ip_obj.department = d['department']
                        ip_obj.mac_address = d['mac_address']
                        ip_obj.save()
                        obj.save()
                except Exception:
                    pass

            print(f"  ✓ 创建设备: {d['hostname']}")


# ==================== 6. DNS 初始化 ====================

def init_dns_server():
    """创建本地DNS服务器实例"""
    from dns.models import DnsServer

    server, created = DnsServer.objects.get_or_create(
        is_local=True,
        defaults={
            'hostname': 'ns.devnets.net',
            'ip_address': '192.168.31.61',
            'bind_version': '9.16.23',
            'named_conf_path': '/etc/named.conf',
            'zone_dir': '/var/named',
            'log_file': '/var/log/named.log',
            'enabled': True,
            'description': '本地BIND9 DNS服务器 (源码编译安装)',
        }
    )

    if created:
        print(f"  ✓ 创建DNS服务器: {server.hostname} ({server.ip_address})")
    else:
        print(f"  DNS服务器已存在: {server.hostname}")

    return server


def init_dns_global_option(server):
    """创建全局配置选项"""
    from dns.models import DnsGlobalOption

    opt, created = DnsGlobalOption.objects.get_or_create(
        server=server,
        defaults={
            # 基础选项
            'directory': '/var/named',
            # 监听地址
            'listen_on_v4': 'any',
            'listen_on_v6': 'any',
            # 查询控制 (留空让View控制)
            'allow_query': '',
            'allow_recursion': '',
            'recursion': True,
            # 安全选项
            'dnssec_validation': 'no',
            'auth_nxdomain': False,
            'empty_zones_enable': True,
            # 转发设置
            'forward_policy': 'first',
            'forwarders': '119.29.29.29\n223.5.5.5',
            # 日志/性能
            'querylog_enable': True,
            'max_cache_size': '1G',
            'version_hide': True,
        }
    )

    if created:
        print(f"  ✓ 创建全局配置: recursion=yes, forwarders=[腾讯DNS/阿里DNS]")
    else:
        print(f"  全局配置已存在")

    return opt


def init_dns_acls():
    """创建常用ACL定义"""
    from dns.models import DnsAcl, DnsAclItem

    acls_config = {
        'IDC': {
            'description': 'IDC内网网段',
            'built_in': False,
            'items': [
                ('cidr', '192.168.0.0/16', 0),
                ('cidr', '172.16.0.0/12', 1),
                ('cidr', '10.0.0.0/8', 2),
                ('localhost', '', 3),
            ],
        },
        'Trusted': {
            'description': '受信任的管理网络',
            'built_in': False,
            'items': [
                ('cidr', '192.168.31.0/24', 0),
                ('localhost', '', 1),
            ],
        },
        'SlaveServers': {
            'description': '允许Zone传输的从服务器列表',
            'built_in': False,
            'items': [],   # 预留空列表，按需填写
        },
    }

    acl_map = {}
    for acl_name, config in acls_config.items():
        acl, created = DnsAcl.objects.get_or_create(
            name=acl_name,
            defaults={'description': config['description'], 'built_in': config['built_in']}
        )

        if created and config['items']:
            items = []
            for item_type, value, order_idx in config['items']:
                items.append(DnsAclItem(
                    acl=acl, item_type=item_type, value=value, order_index=order_idx
                ))
            DnsAclItem.objects.bulk_create(items)

        acl_map[acl_name] = acl
        item_count = acl.items.count()
        print(f"  ✓ 创建ACL: {acl_name} ({item_count}条规则)")

    return acl_map


def init_dns_view(acl_map):
    """创建默认View视图"""
    from dns.models import DnsView

    view, created = DnsView.objects.get_or_create(
        name='IDC_View',
        defaults={
            'description': 'IDC内部视图 - 匹配内网客户端',
            'order_index': 10,
        }
    )

    if created:
        # 关联匹配目标ACL (match_destinations)
        idc_acl = acl_map.get('IDC')
        trusted_acl = acl_map.get('Trusted')
        if idc_acl:
            view.match_destinations.add(idc_acl)
        if trusted_acl:
            view.match_clients.add(trusted_acl)
        # View级别查询控制
        if idc_acl:
            view.allow_query_acl = idc_acl
            view.allow_recursion_acl = idc_acl
        view.save()

        print(f"  ✓ 创建View: IDC_View (allow_query/recursion -> ID)")
    else:
        print(f"  View已存在: IDC_View")

    return view


def init_dns_zone(view):
    """创建示例正向区域 devnets.net"""
    from dns.models import DnsZone, DnsRecord
    from datetime import date

    zone_name = 'devnets.net'
    today_serial = int(f"{date.today().strftime('%Y%m%d')}01")

    zone, created = DnsZone.objects.get_or_create(
        name=zone_name,
        defaults={
            'zone_type': 'master',
            'direction_type': 'forward',
            'view': view,
            'default_ttl': 3600,
            # SOA 参数
            'primary_ns': 'ns.devnets.net.',
            'admin_mail': 'admin.devnets.net.',
            'serial_no': today_serial,
            'refresh': 3600,
            'retry': 600,
            'expire': 86400,
            'minimum': 3600,
            'enabled': True,
            'description': '开发测试网络主域名',
        }
    )

    if not created:
        print(f"  区域已存在: {zone_name}")
        return zone

    # 创建标准资源记录
    records = [
        # SOA 记录 (自动生成)
        {'record_type': 'SOA', 'name': '@',
         'value': f'ns.devnets.net. admin.devnets.net. ( {today_serial} 3600 600 86400 3600 )'},
        # NS 记录
        {'record_type': 'NS', 'name': '@', 'value': 'ns.devnets.net.'},
        # NS 的 A 记录
        {'record_type': 'A', 'name': 'ns', 'value': '192.168.31.61'},
        # 常用主机记录
        {'record_type': 'A', 'name': 'www', 'value': '192.168.100.10'},
        {'record_type': 'A', 'name': 'api', 'value': '192.168.100.11'},
        {'record_type': 'A', 'name': 'db', 'value': '192.168.100.12'},
        {'record_type': 'AAAA', 'name': 'ipv6-test', 'value': '::1'},
        # CNAME 别名
        {'record_type': 'CNAME', 'name': 'web', 'value': 'www.'},
        # MX 邮件
        {'record_type': 'MX', 'name': '@', 'value': 'mail.devnets.net.', 'priority': 10},
        # TXT 验证
        {'record_type': 'TXT', 'name': '@', 'value': '"v=spf1 mx -all"'},
    ]

    rec_objs = []
    for rec_data in records:
        rec_objs.append(DnsRecord(zone=zone, **rec_data))

    DnsRecord.objects.bulk_create(rec_objs)

    record_count = len(rec_objs)
    print(f"  ✓ 创建区域: [{zone.get_zone_type_display()}] {zone_name} ({record_count}条记录)")

    return zone


def init_dns_reverse_zone(view):
    """创建示例反向区域 31.168.192.in-addr.arpa (对应 192.168.31.0/24)"""
    from dns.models import DnsZone, DnsRecord
    from datetime import date

    zone_name = '31.168.192.in-addr.arpa'
    today_serial = int(f"{date.today().strftime('%Y%m%d')}01")

    zone, created = DnsZone.objects.get_or_create(
        name=zone_name,
        defaults={
            'zone_type': 'master',
            'direction_type': 'reverse',
            'view': view,
            'default_ttl': 3600,
            'primary_ns': 'ns.devnets.net.',
            'admin_mail': 'admin.devnets.net.',
            'serial_no': today_serial,
            'refresh': 3600,
            'retry': 600,
            'expire': 86400,
            'minimum': 3600,
            'enabled': True,
            'description': '管理网络反向解析 (192.168.31.0/24)',
        }
    )

    if not created:
        print(f"  反向区域已存在: {zone_name}")
        return zone

    records = [
        {'record_type': 'SOA', 'name': '@',
         'value': f'ns.devnets.net. admin.devnets.net. ( {today_serial} 3600 600 86400 3600 )'},
        {'record_type': 'NS', 'name': '@', 'value': 'ns.devnets.net.'},
        {'record_type': 'PTR', 'name': '61', 'value': 'ns.devnets.net.'},
        {'record_type': 'PTR', 'name': '2', 'value': 'switch-core.devnets.net.'},
        {'record_type': 'PTR', 'name': '1', 'value': 'gw-mgmt.devnets.net.'},
    ]

    rec_objs = [DnsRecord(zone=zone, **r) for r in records]
    DnsRecord.objects.bulk_create(rec_objs)

    print(f"  ✓ 创建反向区域: [reverse] {zone_name} ({len(rec_objs)}条记录)")

    return zone


# ==================== 主流程 ====================

def main():
    minimal_mode = '--minimal' in sys.argv or '-m' in sys.argv

    print("\n" + "=" * 60)
    print("       DDI管理系统 数据初始化")
    if minimal_mode:
        print("       模式: 最小化 (仅基础配置)")
    else:
        print("       模式: 完整 (含示例数据)")
    print("=" * 60 + "\n")

    # ---- 必要的基础初始化 ----
    print("[1/7] 创建系统角色...")
    create_roles()

    print("\n[2/7] 创建管理员账户...")
    create_admin_user()

    print("\n[3/7] 初始化DNS服务器...")
    dns_server = init_dns_server()

    print("\n[4/7] 初始化DNS全局配置...")
    init_dns_global_option(dns_server)

    print("\n[5/7] 初始化DNS ACL...")
    acl_map = init_dns_acls()

    print("\n[6/7] 初始化DNS View 和 Zone...")
    dns_view = init_dns_view(acl_map)
    init_dns_zone(dns_view)
    init_dns_reverse_zone(dns_view)

    # ---- 可选的示例数据 ----
    if not minimal_mode:
        print("\n[7/7] 创建示例区域/VLAN/子网/设备...")
        create_sample_regions()
        sample_vlans()
        sample_subnets()
        sample_switch_devices()
        sample_devices()
    else:
        print("\n[7/7] 跳过示例数据 (使用 --minimal 或 -m 可跳过此步)")

    print("\n" + "=" * 60)
    print("  ✅ 初始化完成！")
    print("=" * 60)
    print("\n📌 访问信息:")
    print("   地址: http://127.0.0.1:8000/")
    print("   用户名: admin")
    print("   密码: Admin@123")
    print("\n📋 已初始化内容:")
    print("   角色: 系统管理员 / 网络管理员 / 运维人员 / 审计用户")
    print(f"   DNS服务器: {dns_server.hostname} (BIND {dns_server.bind_version})")
    print("   ACL: ID(内网) / Trusted(管理网) / SlaveServers")
    print("   View: IDC_View (内网视图)")
    print("   Zone: devnets.net (正向) + 31.168.192.in-addr.arpa (反向)")
    if not minimal_mode:
        print("   IPAM: 4个区域 / 5个VLAN / 5个子网 / 多台设备")
    print()


if __name__ == '__main__':
    main()
