# DDI System

基于 `Python + Django + Django REST Framework + Celery + MySQL` 的 DDI 管理平台，提供统一的 Web 管理入口，用于维护 IPAM、DNS、DHCP、任务中心、审计日志和系统健康状态。

当前项目使用 Django Templates 作为前端，Docker Compose 以 4 个容器部署：

- `ddi-web`：Django Web、REST API、RBAC、任务调度、审计、仪表盘
- `ddi-mysql`：业务数据库、PowerDNS 后端数据库、Kea Lease 数据库
- `ddi-pdns`：PowerDNS Authoritative + API，外部提供 DNS 解析
- `ddi-kea`：Kea DHCP4/6 + Control Agent，外部提供 DHCP 服务

## 架构说明

- 浏览器只访问 `ddi-web`
- DNS 客户端直接访问 `ddi-pdns:53/tcp,53/udp`
- DHCP 客户端直接访问 `ddi-kea:67/udp,547/udp`
- `ddi-web` 通过 PowerDNS API 管理 DNS
- `ddi-web` 通过 Kea Control Agent 管理 DHCP
- 配置下发通过任务中心异步执行
- 审计日志记录关键管理操作

`ddi-web` 不承载 DNS 查询流量和 DHCP 地址分配流量，只负责管理面。

## 当前功能

### 1. 账户与权限

- 用户、角色、权限、登录日志
- Session 登录
- JWT / Token / Session 认证并存
- RBAC 权限校验

### 2. IPAM

- 地址空间管理
- 网段管理
- 自动生成网段 IP 清单
- IP 地址分配、释放、预留、禁用
- IP 使用历史
- 地址利用率统计
- Excel 导入导出

### 3. DNS

- PowerDNS 服务配置
- Zone 管理
- 记录管理
- 批量删除记录
- PowerDNS 同步、比对、下发
- DNS 变更日志
- 递归转发配置页面

### 4. DHCP

- Kea 服务配置
- DHCP 子网管理
- 地址池管理
- 保留地址管理
- DHCP Option 管理
- 当前租约
- 租约历史
- DHCP 配置测试、下发、重载
- Kea Lease 同步
- 跨三层 Relay 地址支持

### 5. 运维与系统

- 仪表盘
- 任务中心
- 审计日志
- 健康检查
- 系统配置

## 已移除功能

- “联动管理”菜单和 UI 入口已移除
- `/ui/linkage/...` 页面当前返回 `404`

## 目录结构

```text
accounts/   用户、角色、权限、登录
audit/      审计日志与中间件
common/     通用响应、权限、审计工具
dhcp/       Kea 模型、API、服务、客户端
dns/        PowerDNS 模型、API、服务、客户端
ipam/       地址空间、网段、IP 地址、利用率
system/     仪表盘、系统配置、健康检查、统一页面
tasks/      异步任务、任务日志、Celery 执行
docker/     ddi-web / pdns / kea / mysql 启动配置
templates/  Django 模板
static/     CSS / JS
tests/      基础测试
```

## 快速启动

### Docker Compose

```bash
docker compose up -d --build
```

首次启动会自动执行：

- 等待 MySQL 就绪
- Django `makemigrations`
- Django `migrate`
- 初始化 RBAC 权限
- 收集静态文件
- 创建默认管理员账号
- 启动 Gunicorn
- 在 `ddi-web` 容器内启动 Celery Worker

访问地址：

- 管理平台：`http://<server-ip>:8000/`
- Django Admin：`http://<server-ip>:8000/admin/`

默认管理员：

- 用户名：`admin`
- 密码：`admin123456`

### 停止与重建

```bash
docker compose down
docker compose up -d --build
```

如果数据库初始化异常，需要清理卷后重建：

```bash
docker compose down -v
docker compose up -d --build
```

### 离线安装包

当前仓库已经提供离线交付方案，适合“打包机可联网、安装机不可联网”的场景。

在线打包机执行：

```bash
bash scripts/build_offline_bundle.sh
```

默认会生成：

- `offline_bundle/images/`：离线镜像 tar 包
- `offline_bundle/package/`：离线部署文件
- `offline_bundle/ddi-offline-bundle.tar.gz`：可直接拷贝的整体安装包

离线目标机执行：

```bash
tar -xzf ddi-offline-bundle.tar.gz
cd offline_bundle/package
cp .env.example .env
bash scripts/install.sh
```

离线模式使用：

- [docker-compose.offline.yml](/opt/codebuddy/ddi_system/docker-compose.offline.yml)
- [scripts/build_offline_bundle.sh](/opt/codebuddy/ddi_system/scripts/build_offline_bundle.sh)
- [scripts/install_offline_bundle.sh](/opt/codebuddy/ddi_system/scripts/install_offline_bundle.sh)

说明：

- 离线安装机需要预先安装好 Docker Engine 和 Docker Compose 插件
- 离线包内已经包含 `ddi-web`、`ddi-pdns`、`ddi-kea`、`mysql:8.4` 镜像
- 打包机与安装机应保持相同 CPU 架构，例如都为 `x86_64`

## 容器与端口

### `ddi-web`

- 端口：`8000/tcp`
- 作用：Web UI、REST API、Celery Worker

### `ddi-mysql`

- 端口：`3306/tcp`
- 数据库：
  - `ddi_system`
  - `powerdns`
  - `kea`

### `ddi-pdns`

- 端口：`53/tcp`
- 端口：`53/udp`
- 端口：`8081/tcp`
- 作用：权威 DNS + PowerDNS API

### `ddi-kea`

- 端口：`67/udp`
- 端口：`547/udp`
- 内部暴露：`8000/tcp`
- 作用：Kea DHCP + Control Agent

## 关键环境变量

`docker-compose.yml` 已内置默认值，常用变量如下：

```env
DJANGO_SECRET_KEY=change-me-please
DJANGO_ALLOWED_HOSTS=*
MYSQL_HOST=ddi-mysql
MYSQL_PORT=3306
MYSQL_DATABASE=ddi_system
MYSQL_USER=ddi
MYSQL_PASSWORD=ddi_password
PDNS_API_URL=http://ddi-pdns:8081
PDNS_API_KEY=ddi-pdns-key
KEA_API_URL=http://ddi-kea:8000
KEA_LEASE_DB_HOST=ddi-mysql
KEA_LEASE_DB_PORT=3306
KEA_LEASE_DB_NAME=kea
KEA_LEASE_DB_USER=ddi
KEA_LEASE_DB_PASSWORD=ddi_password
TIME_ZONE=Asia/Shanghai
```

## 数据初始化

MySQL 初始化脚本位于：

- [docker/mysql/init/01-create-databases.sql](/opt/codebuddy/ddi_system/docker/mysql/init/01-create-databases.sql)

它会：

- 创建 `ddi_system`、`powerdns`、`kea`
- 给 `ddi` 用户授权
- 初始化 PowerDNS 所需表结构

## 本地开发

### 1. 创建虚拟环境

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### 2. 使用 SQLite 进行本地开发

```bash
export SQLITE_DATABASE=/tmp/ddi.sqlite3
export DJANGO_DEBUG=true
python manage.py migrate
python manage.py init_rbac
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

访问：

- `http://127.0.0.1:8000/`

## 测试

当前仓库包含基础测试：

- [tests/test_smoke.py](/opt/codebuddy/ddi_system/tests/test_smoke.py)
- [tests/test_ipam_phase2.py](/opt/codebuddy/ddi_system/tests/test_ipam_phase2.py)
- [tests/test_web_auth.py](/opt/codebuddy/ddi_system/tests/test_web_auth.py)

运行方式：

```bash
SQLITE_DATABASE=/tmp/ddi_test.sqlite3 DJANGO_DEBUG=true python manage.py test tests
```

## Web 页面入口

- `/` 或 `/dashboard/`：首页仪表盘
- `/ui/ipam/address-spaces/`：地址空间
- `/ui/ipam/subnets/`：网段管理
- `/ui/ipam/ip-addresses/`：IP 地址管理
- `/ui/ipam/utilization/`：地址利用率
- `/ui/ipam/histories/`：IP 使用历史
- `/ui/dns/service/`：DNS 服务配置
- `/ui/dns/zones/`：Zone 管理
- `/ui/dns/records/`：记录管理
- `/ui/dns/sync/`：DNS 数据同步
- `/ui/dns/change-logs/`：DNS 变更日志
- `/ui/dhcp/service/`：Kea 服务配置
- `/ui/dhcp/subnets/`：DHCP 子网
- `/ui/dhcp/pools/`：地址池管理
- `/ui/dhcp/reservations/`：保留地址
- `/ui/dhcp/options/`：DHCP Option
- `/ui/dhcp/leases/`：当前租约
- `/ui/dhcp/lease-history/`：租约历史
- `/ui/dhcp/deploy/`：DHCP 配置下发
- `/ui/tasks/list/`：任务列表
- `/ui/tasks/logs/`：任务日志
- `/ui/tasks/failed/`：失败任务
- `/ui/audit/operations/`：操作审计
- `/ui/audit/login/`：登录日志
- `/ui/audit/changes/`：配置变更日志
- `/ui/system/users/`：用户管理
- `/ui/system/roles/`：角色管理
- `/ui/system/permissions/`：权限管理
- `/ui/system/configs/`：系统配置
- `/ui/system/health/`：健康检查

## 主要 API

### 认证与用户

- `POST /api/auth/login/`
- `POST /api/auth/logout/`
- `GET /api/auth/profile/`
- `POST /api/auth/change-password/`
- `GET /api/users/`
- `POST /api/users/`
- `GET /api/roles/`
- `POST /api/roles/`
- `GET /api/permissions/`
- `GET /api/login-logs/`

### IPAM

- `GET /api/ipam/address-spaces/`
- `POST /api/ipam/address-spaces/`
- `GET /api/ipam/subnets/`
- `POST /api/ipam/subnets/`
- `POST /api/ipam/subnets/{id}/generate-ips/`
- `GET /api/ipam/subnets/{id}/utilization/`
- `GET /api/ipam/ip-addresses/`
- `POST /api/ipam/ip-addresses/{id}/allocate/`
- `POST /api/ipam/ip-addresses/{id}/release/`
- `POST /api/ipam/ip-addresses/{id}/reserve/`
- `POST /api/ipam/ip-addresses/{id}/disable/`
- `GET /api/ipam/ip-addresses/{id}/histories/`
- `GET /api/ipam/utilization/`
- `GET /api/ipam/subnets/export-excel/`
- `POST /api/ipam/subnets/import-excel/`
- `GET /api/ipam/ip-addresses/export-excel/`
- `POST /api/ipam/ip-addresses/import-excel/`

### DNS

- `GET /api/dns/config/`
- `PUT /api/dns/config/`
- `POST /api/dns/test-connection/`
- `GET /api/dns/zones/`
- `POST /api/dns/zones/`
- `POST /api/dns/zones/sync-from-pdns/`
- `POST /api/dns/zones/{id}/push-to-pdns/`
- `GET /api/dns/records/`
- `POST /api/dns/records/`
- `POST /api/dns/records/bulk-create/`
- `POST /api/dns/records/bulk-delete/`
- `POST /api/dns/records/sync-from-pdns/`
- `POST /api/dns/records/compare/`
- `POST /api/dns/records/{id}/push-to-pdns/`
- `GET /api/dns/change-logs/`

### DHCP

- `GET /api/dhcp/config/`
- `PUT /api/dhcp/config/`
- `POST /api/dhcp/test-connection/`
- `GET /api/dhcp/status/`
- `GET /api/dhcp/config-current/`
- `POST /api/dhcp/config-test/`
- `POST /api/dhcp/config-set/`
- `POST /api/dhcp/config-reload/`
- `GET /api/dhcp/subnets/`
- `POST /api/dhcp/subnets/`
- `GET /api/dhcp/pools/`
- `POST /api/dhcp/pools/`
- `GET /api/dhcp/reservations/`
- `POST /api/dhcp/reservations/`
- `GET /api/dhcp/options/`
- `POST /api/dhcp/options/`
- `GET /api/dhcp/leases/`
- `POST /api/dhcp/leases/sync/`
- `POST /api/dhcp/leases/{id}/release/`
- `POST /api/dhcp/leases/{id}/convert-to-reservation/`

### 任务、审计、健康检查

- `GET /api/tasks/`
- `POST /api/tasks/{id}/retry/`
- `GET /api/tasks/{id}/logs/`
- `GET /api/audit-logs/`
- `GET /api/audit-logs/export/`
- `GET /api/health/`
- `GET /api/health/stats/`
- `GET /api/health/services/`
- `POST /api/health/check-now/`
- `GET /api/health/configs/`

## 响应格式

成功响应：

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "操作成功",
  "data": {}
}
```

失败响应：

```json
{
  "success": false,
  "code": "ERROR_CODE",
  "message": "错误说明",
  "details": {}
}
```

## 当前实现说明

- Celery 使用 `filesystem://` broker，避免额外引入 Redis / RabbitMQ 容器
- `ddi-web` 容器内同时运行 Gunicorn 和 Celery Worker
- DHCP 当前已支持 Relay 地址生成到 Kea `subnet4.relay.ip-addresses`
- IPAM 新建网段后会自动生成网段内 IP 地址清单
- DHCP 租约同步会把 Kea Lease 同步到本地 `DHCPLease`

## 常用运维命令

查看容器状态：

```bash
docker compose ps
```

查看 Web 日志：

```bash
docker compose logs -f ddi-web
```

查看 PowerDNS 日志：

```bash
docker compose logs -f ddi-pdns
```

查看 Kea 日志：

```bash
docker compose logs -f ddi-kea
```

进入 Web 容器：

```bash
docker compose exec ddi-web bash
```

执行 Django 检查：

```bash
docker compose exec ddi-web python manage.py check
```

## 注意事项

- 生产环境请修改 `DJANGO_SECRET_KEY`
- 生产环境请限制 `DJANGO_ALLOWED_HOSTS`
- 默认管理员密码仅用于初始化演示环境
- Kea 与 PowerDNS 的外部业务流量不经过 `ddi-web`
- 由于当前为 4 容器架构，Celery broker 采用文件系统模式，不适合高并发任务场景
