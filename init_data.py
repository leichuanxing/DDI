#!/usr/bin/env python
"""
DDI管理系统初始化脚本
用于创建初始角色、管理员账户和示例数据
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
from dnsmgr.models import DNSZone, DNSRecord
from dhcpmgr.models import DHCPPool, DHCPExclusion, DHCPLease
from devices.models import Device


def create_roles():
    """创建系统角色"""
    roles_data = [
        {'name': '系统管理员', 'code': 'admin', 'description': '系统最高权限，负责用户管理、系统配置'},
        {'name': '网络管理员', 'code': 'network_admin', 'description': '管理子网、VLAN、IP地址、DNS、DHCP等网络资源'},
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
            'name': '访客网络',
            'cidr': '10.0.50.0/24',
            'gateway': '10.0.50.1',
            'purpose': 'guest',
            'vlan_id': 50,
            'region_code': 'OFFICE-A',
        },
    ]

    from ipam.views import SubnetCreateView
    
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
            
            allocated = subnet_obj.ip_addresses.filter(status='allocated').count()
            total = len(ip_objects)
            print(f"  ✓ 创建子网: {subnet_obj.name} ({subnet_obj.cidr}) - 共{total}个IP")


def sample_dns():
    """创建示例DNS数据"""
    zone, _ = DNSZone.objects.get_or_create(
        name='example.com',
        defaults={'zone_type': 'forward', 'primary_dns': '192.168.100.10'}
    )

    records = [
        {'name': '@', 'record_type': 'A', 'value': '192.168.100.100', 'zone': zone},
        {'name': 'www', 'record_type': 'A', 'value': '192.168.100.101', 'zone': zone, 'linked_ip': '192.168.100.101'},
        {'name': 'mail', 'record_type': 'A', 'value': '192.168.100.102', 'zone': zone, 'linked_ip': '192.168.100.102'},
        {'name': 'ftp', 'record_type': 'CNAME', 'value': 'www.example.com.', 'zone': zone},
        {'name': '@', 'record_type': 'MX', 'value': '10 mail.example.com.', 'zone': zone, 'priority': 10},
        {'name': '@', 'record_type': 'NS', 'value': 'ns1.example.com.', 'zone': zone},
        {'name': '_spf', 'record_type': 'TXT', 'value': 'v=spf1 include:_spf.example.com ~all', 'zone': zone},
    ]

    for r in records:
        obj, created = DNSRecord.objects.get_or_create(
            name=r['name'],
            record_type=r['record_type'],
            zone=r['zone'],
            defaults={k: v for k, v in r.items() if k != 'zone'}
        )
        if created:
            print(f"  ✓ 创建DNS记录: {obj}")

    # 反向区域
    rev_zone, _ = DNSZone.objects.get_or_create(
        name='100.168.192.in-addr.arpa',
        defaults={'zone_type': 'reverse'}
    )


def sample_dhcp():
    """创建示例DHCP数据"""
    subnet = Subnet.objects.filter(cidr='192.168.10.0/24').first()
    
    if not subnet:
        print("  ! 跳过DHCP数据（需要先创建子网）")
        return

    pool, created = DHCPPool.objects.get_or_create(
        name='办公网DHCP池',
        defaults={
            'subnet': subnet,
            'start_address': '192.168.10.100',
            'end_address': '192.168.10.200',
            'gateway': '192.168.10.1',
            'dns_servers': '8.8.8.8, 8.8.4.4',
            'lease_time': 86400,
            'status': 'enabled'
        }
    )

    if created:
        DHCPExclusion.objects.create(
            pool=pool,
            start_ip='192.168.10.150',
            end_ip='192.168.10.160',
            reason='打印机固定IP范围'
        )
        
        # 模拟一些租约
        from django.utils import timezone
        import datetime
        
        leases_data = [
            ('192.168.10.101', 'AA:BB:CC:DD:EE:01', 'PC-ZHANGSAN'),
            ('192.168.10.102', 'AA:BB:CC:DD:EE:02', 'PC-LISI'),
            ('192.168.10.103', 'AA:BB:CC:DD:EE:03', 'PHONE-WANGWU'),
        ]
        
        now = timezone.now()
        for ip, mac, hostname in leases_data:
            DHCPLease.objects.create(
                ip_address=ip,
                mac_address=mac,
                hostname=hostname,
                start_time=now - datetime.timedelta(hours=2),
                end_time=now + datetime.timedelta(hours=22),
                status='active',
                pool=pool,
            )
        
        print(f"  ✓ 创建DHCP池: {pool.name}")


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
    ]

    region = Region.objects.first()

    for d in devices:
        obj, created = Device.objects.get_or_create(
            hostname=d['hostname'],
            defaults={**d, 'region': region}
        )
        if created:
            # 关联IP
            try:
                ip_obj = IPAddress.objects.filter(
                    subnet__cidr='192.168.100.0/24',
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


def main():
    print("\n" + "="*60)
    print("       DDI管理系统 数据初始化")
    print("="*60 + "\n")

    print("[1/6] 创建系统角色...")
    create_roles()

    print("\n[2/6] 创建管理员账户...")
    create_admin_user()

    print("\n[3/6] 创建示例区域...")
    create_sample_regions()

    print("\n[4/6] 创建示例VLAN和子网...")
    sample_vlans()
    sample_subnets()

    print("\n[5/6] 创建示例DNS和DHCP数据...")
    sample_dns()
    sample_dhcp()

    print("\n[6/6] 创建示例设备...")
    sample_devices()

    print("\n" + "="*60)
    print("  ✅ 初始化完成！")
    print("="*60)
    print("\n📌 访问信息:")
    print("   地址: http://127.0.0.1:8000/")
    print("   用户名: admin")
    print("   密码: Admin@123\n")


if __name__ == '__main__':
    main()
