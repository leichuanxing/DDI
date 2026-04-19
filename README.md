# 合力数据 DDI 管理系统 v1.0

<p align="center">
  <strong>DDI (DNS + DHCP + IPAM) 网络资源统一管理平台</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue" />
  <img src="https://img.shields.io/badge/Django-4.x-green" />
  <img src="https://img.shields.io/badge/Bootstrap-5.3-purple" />
  <img src="https://img.shields.io/badge/Chart.js-4.x-yellow" />
</p>

---

## 一、项目简介

**合力数据 DDI 管理系统** 是一套基于 **Python / Django** 开发的轻量级 Web 网络基础设施管理平台，统一管理企业内部的 **IP 地址（IPAM）**、**DHCP 地址分配** 和 **DNS 域名解析记录**。系统采用中文本土化设计，内置 DNS/DHCP 服务模拟引擎与网络探测功能，适合中小型企业的网络运维场景。

### 核心亮点

| 特性 | 说明 |
|------|------|
| **DDI 三合一** | IPAM + DNS + DHCP 统一管理，告别分散维护 |
| **网络探测子系统** | 内置 Ping / 端口扫描 / 拓扑发现引擎，后台异步执行 |
| **服务模拟引擎** | DNS 服务端模拟 (~36KB) + DHCP 服务模拟 (~19KB) |
| **服务健康探测** | DNS 记录级别端口可达性探测 + 持久化定时任务 |
| **全链路审计** | 操作日志 + 登录日志双轨记录，支持多维度筛选 |
| **多接口设备** | 支持一台设备多个网卡 (DeviceInterface)，IP 可搜索关联绑定 |
| **轻量依赖** | 仅需 `Django` + `gunicorn` 两个包即可运行 |

---

## 二、功能模块总览

### 界面预览
![alt text](./pic/home_page.png)

### 各模块详细说明

| 模块 | 路由前缀 | 核心功能 |
|------|----------|----------|
| **仪表盘** | `/` | 全局统计卡片（10项指标）、IP使用率饼图、子网柱状图、DNS类型分布饼图、VLAN分布图、告警面板、最近15条操作日志 |
| **IPAM** | `/ipam/` | 区域/VLAN/子网/IP四级层级管理、CIDR自动计算、单IP分配/批量分配/释放保留、Ping探测、端口扫描、实时拓扑图、CSV导出、自动发现规则 |
| **DNS 管理** | `/dns/` | 正向/反向区域管理、7种记录类型(A/AAAA/CNAME/PTR/MX/TXT/NS)、PTR自动建议/FQDN生成、DNS解析在线测试、服务启停控制(转发器/缓存)、健康探测任务、查询日志 |
| **DHCP 管理** | `/dhcp/` | 地址池CRUD(起止地址/网关/DNS/租期)、排除地址范围、租约记录与释放、过期租约检查、DHCP服务启停控制 |
| **设备管理** | `/devices/` | 11种设备类型登记、多网卡接口支持、IP关联绑定(带Select2搜索选择)、设备删除确认、DNS记录联动查询 |
| **用户认证** | `/accounts/` | 登录/登出、用户CRUD(含密码修改)、4种角色(admin/network_admin/operator/auditor)、账号启用禁用、登录成功/失败日志 |
| **审计日志** | `/logs/` | 全量操作记录追溯、按模块/时间/用户筛选、变更前后值对比展示 |

---

## 三、技术栈

| 层面 | 技术 | 版本 |
|------|------|------|
| **后端框架** | Python / Django | >=4.2, <5.0 |
| **前端 UI** | Django Template / Bootstrap 5 / Chart.js / Bootstrap Icons | 5.3 / 4.x / 1.x |
| **前端增强** | Select2 (jQuery插件) | — (CDN引入) |
| **数据库** | SQLite 3 | 可迁移至 MySQL/PostgreSQL |
| **WSGI 服务器** | Gunicorn (生产) / Django Dev Server (开发) | >=21.0 |
| **语言/时区** | 简体中文 (zh-hans) / Asia/Shanghai | — |
| **认证方式** | Django Session Auth (扩展 User 模型) | — |

---

## 四、快速开始

### 前置要求

- Python 3.11+
- pip 包管理器

### 安装步骤

```bash


# 1. 安装依赖
pip install -r requirements.txt

# 2. 数据库迁移
python manage.py makemigrations
python manage.py migrate

# 3. 初始化示例数据（推荐首次运行）
python init_data.py

# 4. 启动开发服务器
python manage.py runserver 0.0.0.0:8000
```

### 访问系统

打开浏览器访问：`http://127.0.0.1:8000/`

| 项目 | 值 |
|------|-----|
| 默认账号 | `admin` |
| 默认密码 | `Admin@123` |

### 快捷脚本启动/停止

```bash
# 开发模式启动
./start.sh dev              # Django runserver, http://0.0.0.0:8000

# 生产模式启动（Gunicorn 后台守护进程）
./start.sh prod             # Gunicorn 4 workers, http://0.0.0.0:8000

# 停止服务（优雅停止 / 强制停止）
./stop.sh                   # 优雅停止
./stop.sh -k                # 强制停止 (SIGKILL)
```

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
├── start.sh                           # 启动脚本 (dev/prod 模式)
├── stop.sh                            # 停止脚本 (优雅/强制)
├── README.md                          # 本文档
│
├── ddi_system/                        # Django 项目配置包
│   ├── settings.py                    # 全局配置 (INSTALLED_APPS/数据库/中间件)
│   ├── urls.py                        # 主路由分发 (7 个模块)
│   ├── wsgi.py                        # WSGI 部署入口
│   └── asgi.py                        # ASGI 异步入口
│
├── accounts/                          # 用户认证与角色管理
│   ├── models.py                      # Role, User(AbstractUser), LoginLog
│   ├── views.py                       # 登录/登出/CRUD/重置密码
│   ├── forms.py                       # 登录/用户创建/编辑表单
│   └── urls.py                        # 路由定义
│
├── dashboard/                         # 首页仪表盘
│   ├── views.py                       # index() 统计聚合视图
│   └── templates/index.html           # 仪表盘页面 (卡片+图表)
│
├── ipam/                              # IP 地址管理 (最复杂模块)
│   ├── models.py                      # Region, VLAN, Subnet, IPAddress
│   ├── views.py                       # CRUD + 分配/释放/批量操作
│   ├── forms.py                       # CIDR/MAC 校验表单
│   ├── scan_models.py                 # ScanTask/DiscoveryRule/ProbeResult/TopologyNode
│   ├── scan_views.py                  # 探测视图
│   ├── scanner.py                     # Ping/端口扫描/TCP引擎
│   └── urls.py                        # 含探测 API 共 28 条路由
│
├── dnsmgr/                            # DNS 管理 (最大模块)
│   ├── models.py                      # DNSSettings/DNSZone/DNSRecord/ProbeTask/DNSQueryLog
│   ├── views.py                       # 区域/记录/探测/解析测试/服务配置
│   ├── forms.py                       # DNS 记录表单 (7种类型智能字段)
│   ├── dns_server.py                  # DNS 服务核心实现 (~36KB)
│   └── urls.py                        # 共 20 条路由
│
├── dhcpmgr/                           # DHCP 管理
│   ├── models.py                      # DHCPPool/DHCPExclusion/DHCPLease
│   ├── views.py                       # 地址池/排除/租约/DHCP 服务
│   ├── dhcp_server.py                 # DHCP 服务模拟 (~19KB)
│   └── urls.py                        # 共 14 条路由
│
├── devices/                           # 设备/主机管理
│   ├── models.py                      # Device, DeviceInterface (多网卡)
│   ├── views.py                       # 设备 CRUD + IP 关联
│   ├── forms.py                       # 设备表单 (含 IP 地址 Select2 搜索)
│   └── urls.py                        # 共 6 条路由
│
├── logs/                              # 日志审计
│   ├── models.py                      # OperationLog
│   ├── views.py                       # 操作日志列表与筛选
│   └── urls.py                        # 操作日志路由
│
├── common/                            # 公共工具包
│   ├── ip_utils.py                    # IP 工具 (CIDR验证/PTR生成/网段计算)
│   └── logger.py                      # 操作日志统一记录器
│
└── templates/                         # HTML 模板 (47 个文件)
    ├── base.html                      # 布局基座 (固定侧边栏 + 顶栏 + 响应式)
    ├── accounts/                      # 登录页/用户列表/表单/登录日志
    ├── dashboard/                     # 仪表盘 (统计卡片 + 4 组 Chart.js 图表)
    ├── ipam/                          # 区域/VLAN/子网/IP 列表详情表单 + 探测全套页面
    ├── dnsmgr/                        # DNS 服务页(缓存按钮组)/区域详情/记录表单/探测/解析日志
    ├── dhcpmgr/                       # 地址池详情/租约列表/排除/服务状态
    ├── devices/                       # 设备列表/详情/表单/删除确认
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
| `/devices/` | 设备 | `(list)`, `create`, `<pk>/edit`, `<pk>/delete`, `<pk>/link-ip/<ip>` | 6 |
| `/logs/` | 日志 | `operation_log` | 1 |

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
- 4 个统计卡片 (运行状态/累计查询/缓存条目/区域数)
- 4 组 Chart.js 图表: IP使用率环形图、子网堆叠柱状图、DNS记录类型分布饼图、VLAN横向柱状图
- 告警面板 (高使用率/冲突IP检测)
- 最近操作记录

### 左侧导航栏
- 固定侧边栏，展开态 / 收起态
- 6 个一级菜单分组 + 折叠二级菜单
- 当前页面精确高亮
- 底部显示当前用户信息

### DNS 服务管理页
- 外部转发器地址输入框 + 启用开关一体化布局
- 查询缓存开关 (按钮组 [开启][关闭])
- 配置摘要面板 + 公共DNS快捷添加
- 解析流程可视化步骤

### 设备管理
- 设备列表 (含删除按钮)
- 编辑时可搜索关联 IP 地址 (Select2 下拉框)
- 删除二次确认页面

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

## 联系作者(请备注软件名称)
![微信二维码](./pic/wx.png)

---

## 许可证

Apache License 2.0

Copyright (c) 2026 合力数据 (HeliData). All rights reserved.
