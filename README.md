# 合力数据 DDI 管理系统 v1.0

<p align="center">
  <strong>DDI (DNS + DHCP + IPAM) 网络资源统一管理平台</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue" />
  <img src="https://img.shields.io/badge/Django-4.x-green" />
  <img src="https://img.shields.io/badge/Bootstrap-5.3-purple" />
  <img src="https://img.shields.io/badge/License-MIT-orange" />
</p>

---

## 一、项目简介

合力数据 DDI 管理系统是一个基于 **Python + Django** 开发的轻量级网络资源管理平台，统一管理企业内部的 **IP 地址（IPAM）**、**DHCP 地址分配** 和 **DNS 解析记录**。系统采用中文本土化设计，内置服务模拟引擎与网络探测功能，适合中小型企业的网络运维场景。

### 核心亮点

| 特性 | 说明 |
|------|------|
| **DDI 三合一** | IPAM + DNS + DHCP 统一管理，告别分散维护 |
| **网络探测子系统** | 内置 Ping / 端口扫描 / 拓扑发现引擎 |
| **服务模拟引擎** | DNS 服务端模拟 (~36KB) + DHCP 服务模拟 (~19KB) |
| **服务健康探测** | DNS 记录级别端口可达性探测 + 持久化定时任务 |
| **全链路审计** | 操作日志 + 登录日志双轨记录 |
| **多接口设备** | 支持一台设备多个网卡 (DeviceInterface) |
| **轻量依赖** | 仅需 `Django` + `gunicorn` 两个包 |

---

## 二、功能模块总览

```
┌─────────────────────────────────────────────────────────────┐
│                     合力数据 DDI 管理系统                      │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│   IPAM   │   DNS    │   DHCP   │  设备管理  │    系统管理     │
│          │          │          │            │                │
│ 区域管理  │ 正向区域  │ 地址池    │ 设备主机   │ 用户管理        │
│ VLAN管理  │ 反向区域  │ 排除地址  │ 多网卡     │ 角色权限        │
│ 子网管理  │ A/AAAA   │ 租约管理  │ IP关联    │ 操作日志        │
│ IP地址   │ CNAME    │ 服务启停  │ DNS联动   │ 登录日志        │
│          │ PTR/MX   │          │           │                │
│ 网络探测  │ TXT/NS   │          │           │                │
│ Ping检测  │ 解析日志  │          │           │                │
│ 端口扫描  │ 服务探测  │          │           │                │
│ 实时拓扑  │ 在线测试  │          │           │                │
└──────────┴──────────┴──────────┴──────────┴────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │     首页仪表盘      │
                    │  统计卡片 / 图表    │
                    │  告警 / 最近操作    │
                    └───────────────────┘
```

### 各模块详细说明

| 模块 | 路由前缀 | 数据模型 | 核心功能 |
|------|----------|----------|----------|
| **仪表盘** | `/` | — | 全局统计卡片、IP 使用率饼图、子网柱状图、DNS 类型分布、VLAN 分布图、告警面板、最近 15 条操作日志 |
| **IPAM** | `/ipam/` | Region, VLAN, Subnet, IPAddress (+4 扫描模型) | 区域/园区管理、VLAN 管理、CIDR 子网 CRUD 与自动计算、IP 分配/释放/保留/批量分配、Ping 探测、端口扫描、实时拓扑图、探测历史与规则 |
| **DNS 管理** | `/dns/` | DNSSettings, DNSZone, DNSRecord, ProbeTask, DNSQueryLog | 正向/反向区域、7 种记录类型(A/AAAA/CNAME/PTR/MX/TXT/NS)、PTR 自动建议、FQDN 生成、DNS 解析在线测试、服务健康探测、持久化探测任务、解析日志(本地/转发/缓存/NXDOMAIN) |
| **DHCP 管理** | `/dhcp/` | DHCPPool, DHCPExclusion, DHCPLease | 地址池 CRUD(起止地址/网关/DNS/租期)、排除地址范围、租约记录(IP-MAC-租期)、DHCP 服务启停控制、过期租约检查 |
| **设备管理** | `/devices/` | Device, DeviceInterface | 11 种设备类型登记、多网卡接口支持、IP 关联绑定、DNS 记录联动查询 |
| **用户认证** | `/accounts/` | Role, User(AbstractUser), LoginLog | 登录/登出、用户 CRUD(含编辑时修改密码)、4 种角色(admin/network_admin/operator/auditor)、密码重置、登录成功/失败日志 |

---

## 三、技术栈

| 层面 | 技术 | 版本 |
|------|------|------|
| **后端框架** | Python / Django | >=4.2, <5.0 |
| **前端 UI** | Django Template / Bootstrap 5 / Chart.js / Bootstrap Icons | 5.3.2 / 4.4.1 / 1.11.1 |
| **数据库** | SQLite 3 | 可迁移至 MySQL/PostgreSQL |
| **WSGI 服务器** | Gunicorn | >=21.0.0 |
| **语言/时区** | 简体中文 (zh-hans) / Asia/Shanghai | — |
| **认证方式** | Django Session Auth (扩展 User 模型) | — |

---

## 四、快速开始

### 前置要求

- Python 3.11+
- pip 包管理器

### 安装步骤

```bash
# 1. 进入项目目录
cd ddi_system

# 2. 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate      # Linux/macOS
# 或: venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 数据库迁移
python manage.py makemigrations
python manage.py migrate

# 5. 初始化示例数据（推荐首次运行）
python init_data.py

# 6. 启动开发服务器
python manage.py runserver 0.0.0.0:8000
```

### 访问系统

打开浏览器访问：`http://127.0.0.1:8000/`

| 项目 | 值 |
|------|-----|
| 默认账号 | `admin` |
| 默认密码 | `Admin@123` |

### 生产环境部署

```bash
# 收集静态文件
python manage.py collectstatic

# 使用 Gunicorn 启动
gunicorn ddi_system.wsgi --bind 0.0.0.0:8000 --workers 4
```

---

## 五、项目结构

```
ddi_system/
├── manage.py                          # Django 入口文件
├── init_data.py                       # 初始化数据脚本 (角色/管理员/示例数据)
├── requirements.txt                   # 依赖: Django + gunicorn
├── README.md                          # 本文档
│
├── ddi_system/                        # Django 项目配置包
│   ├── __init__.py
│   ├── settings.py                    # 全局配置 (INSTALLED_APPS/数据库/中间件)
│   ├── urls.py                        # 主路由分发 (8 个模块)
│   ├── wsgi.py                        # WSGI 部署入口
│   └── asgi.py                        # ASGI 异步入口
│
├── accounts/                          # 用户认证与角色管理
│   ├── models.py                      # Role, User(AbstractUser), LoginLog
│   ├── views.py                       # 登录/登出/CRUD/重置密码
│   ├── forms.py                       # LoginForm/UserCreateForm/UserEditForm
│   └── urls.py                        # 9 条路由
│
├── dashboard/                         # 首页仪表盘
│   ├── views.py                       # index() 统计聚合视图
│   └── urls.py                        # 首页路由
│
├── ipam/                              # IP 地址管理 (IPAM) — 最复杂模块
│   ├── models.py                      # Region, VLAN, Subnet, IPAddress
│   ├── views.py                       # CRUD + 分配/释放/批量操作
│   ├── forms.py                       # CIDR/MAC 校验表单
│   ├── scan_models.py                 # ScanTask/DiscoveryRule/ProbeResult/TopologyNode
│   ├── scan_views.py                  # 探测视图 (19KB)
│   ├── scan_forms.py                  # 探测表单
│   ├── scanner.py                     # Ping/端口扫描/TCP引擎 (18KB)
│   └── urls.py                        # 28 条路由 (含探测 API)
│
├── dnsmgr/                            # DNS 管理 — 最大模块
│   ├── models.py                      # DNSSettings/DNSZone/DNSRecord/ProbeTask/DNSQueryLog
│   ├── views.py                       # 区域/记录/探测/解析测试 (38KB)
│   ├── forms.py                       # DNS 记录表单
│   ├── dns_server.py                  # DNS 服务核心实现 (36KB)
│   └── urls.py                        # 20 条路由
│
├── dhcpmgr/                           # DHCP 管理
│   ├── models.py                      # DHCPPool/DHCPExclusion/DHCPLease
│   ├── views.py                       # 地址池/排除/租约/DHCP 服务
│   ├── forms.py                       # DHCP 表单
│   ├── dhcp_server.py                 # DHCP 服务模拟 (19KB)
│   └── urls.py                        # 14 条路由
│
├── devices/                           # 设备/主机管理
│   ├── models.py                      # Device, DeviceInterface (多网卡)
│   ├── views.py                       # 设备 CRUD + IP 关联
│   ├── forms.py                       # 设备表单
│   └── urls.py                        # 6 条路由
│
├── logs/                              # 日志审计
│   ├── models.py                      # OperationLog
│   ├── views.py                       # 操作日志列表与筛选
│   └── urls.py                        # 1 条路由
│
├── common/                            # 公共工具包
│   ├── ip_utils.py                    # IP 工具 (CIDR验证/PTR生成/网段计算)
│   └── logger.py                      # 操作日志统一记录器
│
└── templates/                         # HTML 模板 (46 个文件)
    ├── base.html                      # 布局基座 (固定侧边栏 + 顶栏 + 响应式)
    ├── accounts/                      # 登录/用户列表/表单/登录日志
    ├── dashboard/                     # 仪表盘 (统计卡片 + 4 组图表)
    ├── ipam/                          # 区域/VLAN/子网/IP 列表详情表单 + 探测全套页面
    ├── dnsmgr/                        # DNS 服务/区域详情/记录表单/探测/解析日志
    ├── dhcpmgr/                       # 地址池详情/租约列表/排除/服务状态
    ├── devices/                       # 设备列表/详情/表单
    └── logs/                          # 操作日志
```

---

## 六、URL 路由一览

| 前缀 | 模块 | 主要路径 | 数量 |
|------|------|----------|------|
| `/admin/` | Django Admin | 后台管理 | — |
| `/accounts/` | 用户认证 | `login`, `logout`, `users/*`, `roles/*`, `login-log/*` | 9 |
| `/dashboard/` | 仪表盘 | `index` (首页) | 1 |
| `/ipam/` | IPAM | `regions/*`, `vlans/*`, `subnets/*`, `ips/*`, `scan/*`, `api/*` | 28 |
| `/dns/` | DNS | `service/*`, `zones/*`, `records/*`, `probe/*`, `query-log/*` | 20 |
| `/dhcp/` | DHCP | `pools/*`, `exclusions/*`, `leases/*`, `service/*` | 14 |
| `/devices/` | 设备 | `(list)`, `create`, `<pk>/edit`, `<pk>/<delete>`, `<pk>/link-ip/<ip>` | 6 |
| `/logs/` | 日志 | `operation_log` | 1 |
| `/` | 首页 | 重定向到 dashboard:index | — |

**总计**: 79+ 条 URL 路由

---

## 七、数据模型概览

```
accounts
├── Role             (id, name, code, description)
├── User             (username, password, email, real_name, phone,
│                     department, role→FK[Role], is_active, last_login_ip)
└── LoginLog         (user→FK[User], username, ip_address, user_agent, status)

ipam
├── Region           (id, name, code, description) [subnet_count, vlan_count]
├── VLAN             (id, vlan_id, name, region→FK[Region], purpose, gateway)
├── Subnet           (id, name, cidr, gateway, prefix_len,
│                     region→FK, vlan→FK, purpose)
│                     [total_ips, allocated_ips, available_ips, usage_percent]
└── IPAddress        (id, ip_address, subnet→FK[Subnet], status, hostname,
                     mac_address, device_name, owner, department, device_type,
                     binding_type, dns_linked, notes, created_by→FK)

dnsmgr
├── DNSSettings      (id, enable_forward, forwarders, listen_port,
│                     default_ttl, listen_address, enable_cache, cache_ttl)
├── DNSZone          (id, name, zone_type, primary_dns)
│                     [record_count, enabled_record_count]
├── DNSRecord        (id, name, record_type, value, ttl, zone→FK,
│                     linked_ip, status, probe_port, priority)
├── ProbeTask        (id, name, target, port, interval, status,
│                     total_probes, reachable_count, history(JSON))
└── DNSQueryLog      (id, query_name, query_type, client_ip,
                     result_source, answer_data, rcode, response_time_ms)

dhcpmgr
├── DHCPPool         (id, name, subnet→FK[Subnet], start_address, end_address,
│                     gateway, dns_servers, lease_time, status)
│                     [total_addresses, allocated_count, available_count]
├── DHCPExclusion    (id, pool→FK, start_ip, end_ip, reason)
└── DHCPLease        (id, ip_address, mac_address, hostname,
                     start_time, end_time, status, pool→FK)

devices
├── Device           (id, hostname, device_name, device_type, manager,
│                     department, mac_address, os, region→FK, ip_address→FK)
│                     [linked_dns_records]
└── DeviceInterface  (id, device→FK, name, mac_address, ip_address→FK, is_primary)

logs
└── OperationLog     (id, user→FK, module, action, object_type,
                     old_value, new_value, ip_address, operation_time)
```

**总计**: 18 个业务数据模型

---

## 八、初始化数据说明

执行 `python init_data.py` 将按顺序创建以下数据：

| 步骤 | 函数 | 创建内容 |
|------|------|----------|
| **1/6** | `create_roles()` | 4 种系统角色: 系统管理员 / 网络管理员 / 运维人员 / 审计用户 |
| **2/6** | `create_admin_user()` | 管理员账户: `admin` / `Admin@123` (邮箱 admin@example.com) |
| **3/6** | `create_sample_regions()` | 4 个区域: 总部机房(HQ)、研发中心(R&D)、办公区A/B栋 |
| **4/6** | `sample_vlans()` + `sample_subnets()` | 5 个 VLAN + 4 个子网 (办公/服务器/DMZ/访客)，自动生成完整 IP 池 |
| **5/6** | `sample_dns()` + `sample_dhcp()` | example.com 正向区域 (8 条记录) + 反向区域; DHCP 地址池 + 排除范围 + 3 条模拟租约 |
| **6/6** | `sample_devices()` | 5 台示例设备 (Web/DB 服务器、交换机、防火墙、PC)，自动关联 IP |

> **注意**: 必须先完成 `migrate` 再运行此脚本。

---

## 九、用户角色体系

| 角色 | 编码 | 权限范围 |
|------|------|----------|
| **系统管理员** | `admin` | 全部权限：用户管理、系统配置、所有模块读写 |
| **网络管理员** | `network_admin` | IPAM / DNS / DHCP 全部资源管理 |
| **运维人员** | `operator` | 资源查询、IP 申请/释放/保留、主机信息维护 |
| **审计用户** | `auditor` | 只读访问：可查看所有资源和变更记录日志 |

---

## 十、核心业务规则

1. **CIDR 校验**: 子网必须符合标准 CIDR 格式 (`192.168.1.0/24`)，创建时自动计算掩码位数
2. **IP 唯一性**: 同一子网内每个 IP 只能有一条记录 (`unique_together`)
3. **状态约束**: 同一 IP 同一时刻只能有一个有效占用状态 (available/allocated/reserved/conflict/disabled)
4. **DHCP 边界**: 地址池起止地址不能超出所属子网范围
5. **DNS 关联**: A 记录绑定的 IP 必须为合法且已存在的 IPAddress
6. **保留保护**: 已标记为 reserved 的 IP 地址不可重复分配
7. **网关保留**: 子网创建时网关地址自动标记为 reserved 状态
8. **删除确认**: 所有删除操作均需要二次确认弹窗
9. **密码强度**: 编辑用户修改密码时需 >=8 位且包含字母和数字
10. **日志上限**: DNS 解析日志最多存储 10000 条，超出自动清理最旧记录

---

## 十一、系统截图预览

### 登录页
- 渐变背景 + 居中卡片布局
- 显示默认账号提示

### 首页仪表盘
- 10 个统计卡片 (IP总数/已分配/空闲/保留/冲突/子网数/DNS记录/DHCP池/活跃租约/设备数)
- 4 组 Chart.js 图表: IP使用率饼图、子网使用柱状图、DNS记录类型分布、VLAN地址分布
- 告警面板 (高使用率/冲突IP检测)
- 最近 15 条操作记录

### 左侧导航栏
- 固定侧边栏，240px 展开态 / 60px 收起态
- 6 个一级菜单分组 + 折叠二级菜单
- 当前页面精确高亮 (url_name 匹配)
- 底部显示当前用户信息

### 各功能页面
- 统一 Bootstrap 5 卡片风格
- 表格支持分页 (20条/页)
- 表单内联校验与错误提示
- 操作按钮带图标 (bi-*)

---

## 十二、扩展建议

本系统为第一阶段基础版本，后续可扩展的方向：

- [ ] RESTful API 接口层 (Django REST Framework)
- [ ] Excel / CSV 批量导入导出
- [ ] BIND / ISC-DHCP 配置文件自动生成与下发
- [ ] 对接真实 DNS (BIND9/PowerDNS) / DHCP (ISC-DHCP/Kea) 服务
- [ ] IPv6 地址全链路管理
- [ ] IP 地址审批工作流与告警通知 (邮件/钉钉/企微)
- [ ] 多租户 / 多组织隔离
- [ ] RBAC 细粒度权限 (对象级别权限控制)
- [ ] 前后端分离 (Vue.js / React 前端)
- [ ] Docker 容器化部署与 Compose 编排

---

![alt text](8c0e6f322ceded647dbc0ba07b8c2802.png)
![alt text](bb054614a6958e5f989de649e626b4bf.png)

## 十三、许可证

Apache License 2.0

Copyright (c) 2026 合力数据 (HeliData). All rights reserved.
