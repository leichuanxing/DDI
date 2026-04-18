# 合力数据 DDI 管理系统 v1.0

## 项目简介

合力数据 DDI 管理系统是一个基于 Python + Django 开发的轻量级网络资源管理平台，统一管理企业内部的 **IP 地址资源（IPAM）**、**DHCP 地址分配** 和 **DNS 解析记录**。

## 功能特性

### 核心功能模块

| 模块 | 功能说明 |
|------|----------|
| **IPAM** | 区域管理、VLAN管理、子网管理、IP地址分配/释放/保留 |
| **DNS管理** | 正向/反向区域管理、A/AAAA/CNAME/PTR/MX/TXT/NS记录 |
| **DHCP管理** | 地址池管理、排除地址、租约记录查看与模拟 |
| **设备管理** | 主机/设备信息登记、关联IP和DNS |
| **日志审计** | 操作日志、登录日志，支持筛选查询 |

## 技术栈

- **后端**: Python 3.11+ / Django 4.x
- **前端**: Django Template / Bootstrap 5 / Chart.js
- **数据库**: SQLite 3 (可迁移至 MySQL/PostgreSQL)

## 快速开始

### 1. 安装依赖

```bash
cd ddi_system
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
python manage.py makemigrations
python manage.py migrate
```

### 3. 初始化示例数据（可选）

```bash
python init_data.py
```

这将创建：
- 4种角色（管理员、网络管理员、运维人员、审计用户）
- 默认管理员账号: `admin` / `Admin@123`
- 示例区域、VLAN、子网及IP地址池
- 示例DNS记录、DHCP池和租约数据
- 示例设备信息

### 4. 启动服务

```bash
# 开发模式
python manage.py runserver 0.0.0.0:8000

# 或使用 Gunicorn 生产部署
gunicorn ddi_system.wsgi --bind 0.0.0.0:8000
```

### 5. 访问系统

打开浏览器访问: `http://127.0.0.1:8000/`

## 用户角色说明

| 角色 | 权限范围 |
|------|----------|
| **系统管理员** | 全部权限，用户管理、系统配置 |
| **网络管理员** | IPAM/DNS/DHCP全部资源管理 |
| **运维人员** | 资源查询、IP申请/释放、主机维护 |
| **审计用户** | 只读访问，查看资源和日志 |

## 项目结构

```
ddi_system/
├── manage.py                 # Django 入口文件
├── init_data.py              # 初始化数据脚本
├── requirements.txt          # 依赖列表
├── ddi_system/               # 项目配置
│   ├── settings.py           # Django 配置
│   ├── urls.py               # 主路由
│   └── wsgi.py/asgi.py       # 部署入口
├── accounts/                 # 用户认证与角色管理
│   ├── models.py             # 用户、角色模型
│   ├── views.py              # 登录/用户CRUD视图
│   └── forms.py              # 表单定义
├── dashboard/                # 首页仪表盘
│   └── views.py              # 统计数据与图表
├── ipam/                     # IP地址管理
│   ├── models.py             # Region/VLAN/Subnet/IPAddress
│   ├── views.py              # CRUD + 分配/释放操作
│   └── forms.py              # 表单校验(CIDR/MAC等)
├── dnsmgr/                   # DNS管理
│   ├── models.py             # Zone/Record
│   └── views.py              # 记录增删改查
├── dhcpmgr/                  # DHCP管理
│   ├── models.py             # Pool/Exclusion/Lease
│   └── views.py              # 地址池与租约管理
├── devices/                  # 设备主机管理
│   └── models.py             # Device
├── logs/                     # 日志审计
│   └── models.py             # OperationLog/LoginLog
├── common/                   # 公共工具
│   ├── logger.py             # 操作日志记录器
│   └── ip_utils.py           # IP工具函数(验证/计算)
└── templates/                # HTML模板
    ├── base.html             # 布局基座(侧边栏+顶栏)
    ├── accounts/             # 登录/用户管理页面
    ├── dashboard/            # 仪表盘(统计卡片+图表)
    ├── ipam/                 # IPAM各模块页面
    ├── dnsmgr/               # DNS管理页面
    ├── dhcpmgr/              # DHCP管理页面
    ├── devices/              # 设备管理页面
    └── logs/                 # 日志展示页面
```

## 核心业务规则

1. 子网必须符合标准 CIDR 格式 (`192.168.1.0/24`)
2. 同一 IP 在同一时刻只能有一个有效占用状态
3. DHCP 地址池起止地址不能超出子网范围
4. DNS A 记录绑定的 IP 必须合法且存在
5. 已保留地址不可重复分配
6. 网关地址默认标记为保留状态
7. 所有删除操作需二次确认

## 扩展建议

本系统为第一阶段基础版本，后续可扩展：

- [ ] Excel/CSV 导入导出
- [ ] API 接口（REST Framework）
- [ ] BIND/DHCP 配置文件自动生成
- [ ] 对接真实 DNS/DHCP 服务 API
- [ ] IPv6 支持
- [ ] 审批流程与告警通知
- [ ] 多租户支持

## 许可证

MIT License
