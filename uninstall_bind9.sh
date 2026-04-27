
#!/usr/bin/env bash
set -euo pipefail

# ==========================================================
# BIND 9.16.23 卸载脚本
# 支持：
#   - Rocky Linux 9
#   - Red Hat Enterprise Linux 9
#   - AlmaLinux 9 / Oracle Linux 9 基本兼容
#
# 对应安装脚本内容：
#   - bind / bind-utils / bind-dnssec-utils
#   - /etc/named.conf
#   - /etc/rndc.key
#   - /etc/systemd/system/named.service
#   - /var/named
#   - /var/log/named
# ==========================================================

# 是否卸载 RPM 软件包
REMOVE_PACKAGES="${REMOVE_PACKAGES:-yes}"

# 是否删除 /etc/named.conf、/etc/rndc.key 等配置文件
REMOVE_CONFIG="${REMOVE_CONFIG:-yes}"

# 是否删除 /var/named 区域数据目录
# 默认 no，防止误删 DNS 区域文件
REMOVE_DATA="${REMOVE_DATA:-no}"

# 是否删除 /var/log/named 日志目录
REMOVE_LOG="${REMOVE_LOG:-yes}"

# 是否删除自定义 systemd 服务文件
REMOVE_SYSTEMD_UNIT="${REMOVE_SYSTEMD_UNIT:-yes}"

# 是否移除 firewalld DNS 放行
REMOVE_FIREWALL="${REMOVE_FIREWALL:-yes}"

# 是否移除 dnf versionlock 锁定
REMOVE_VERSIONLOCK="${REMOVE_VERSIONLOCK:-yes}"

BACKUP_DIR="/root/bind_uninstall_backup_$(date +%F_%H%M%S)"

log() {
    echo -e "\033[1;32m[$(date '+%F %T')] $*\033[0m"
}

warn() {
    echo -e "\033[1;33m[WARN] $*\033[0m"
}

err() {
    echo -e "\033[1;31m[ERROR] $*\033[0m" >&2
}

die() {
    err "$*"
    exit 1
}

if [[ "$EUID" -ne 0 ]]; then
    die "请使用 root 用户执行脚本"
fi

log "开始卸载 BIND"

if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    log "当前系统：${PRETTY_NAME:-unknown}"
else
    warn "未找到 /etc/os-release，跳过系统版本识别"
fi

log "创建备份目录：${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"

log "备份 BIND 配置文件"

for file in \
    /etc/named.conf \
    /etc/rndc.key \
    /etc/rndc.conf \
    /etc/named.rfc1912.zones \
    /etc/named.root.key \
    /etc/sysconfig/named \
    /etc/systemd/system/named.service \
    /usr/lib/systemd/system/named.service
do
    if [[ -e "$file" ]]; then
        cp -a "$file" "${BACKUP_DIR}/$(basename "$file").bak" 2>/dev/null || true
        log "已备份：$file"
    fi
done

log "备份 BIND 数据目录"

for dir in \
    /var/named \
    /var/log/named \
    /run/named
do
    if [[ -e "$dir" ]]; then
        cp -a "$dir" "${BACKUP_DIR}/$(basename "$dir").bak" 2>/dev/null || true
        log "已备份目录：$dir"
    fi
done

log "停止 named 服务"

systemctl stop named 2>/dev/null || true
systemctl disable named 2>/dev/null || true
systemctl reset-failed named 2>/dev/null || true

if pgrep -x named >/dev/null 2>&1; then
    warn "检测到 named 进程仍在运行，尝试终止"
    pkill -x named || true
    sleep 2
fi

if pgrep -x named >/dev/null 2>&1; then
    warn "named 进程仍未退出，强制终止"
    pkill -9 -x named || true
fi

if [[ "${REMOVE_FIREWALL}" == "yes" ]]; then
    log "移除 firewalld DNS 服务放行"

    if systemctl is-active --quiet firewalld; then
        firewall-cmd --permanent --remove-service=dns 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
        log "已移除 firewalld DNS 放行"
    else
        warn "firewalld 未运行，跳过防火墙处理"
    fi
else
    warn "REMOVE_FIREWALL=no，跳过防火墙处理"
fi

if [[ "${REMOVE_VERSIONLOCK}" == "yes" ]]; then
    log "尝试移除 BIND versionlock 锁定"

    if command -v dnf >/dev/null 2>&1 && dnf versionlock list >/dev/null 2>&1; then
        dnf versionlock delete bind bind-utils bind-libs bind-license bind-dnssec-utils bind-chroot bind-devel python3-bind 2>/dev/null || true
        log "已尝试移除 versionlock"
    else
        warn "versionlock 插件不可用或未启用，跳过"
    fi
else
    warn "REMOVE_VERSIONLOCK=no，跳过 versionlock 处理"
fi

if [[ "${REMOVE_SYSTEMD_UNIT}" == "yes" ]]; then
    log "删除自定义 systemd named.service"

    rm -f /etc/systemd/system/named.service
else
    warn "REMOVE_SYSTEMD_UNIT=no，保留 /etc/systemd/system/named.service"
fi

log "重新加载 systemd"

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

if [[ "${REMOVE_PACKAGES}" == "yes" ]]; then
    log "卸载 BIND 相关 RPM 软件包"

    dnf remove -y \
        bind \
        bind-utils \
        bind-libs \
        bind-license \
        bind-dnssec-utils \
        bind-chroot \
        bind-devel \
        python3-bind \
        2>/dev/null || true
else
    warn "REMOVE_PACKAGES=no，跳过 RPM 软件包卸载"
fi

if [[ "${REMOVE_CONFIG}" == "yes" ]]; then
    log "删除 BIND 配置文件"

    rm -f /etc/named.conf
    rm -f /etc/rndc.key
    rm -f /etc/rndc.conf
    rm -f /etc/named.rfc1912.zones
    rm -f /etc/named.root.key
    rm -f /etc/sysconfig/named

    rm -rf /etc/named
else
    warn "REMOVE_CONFIG=no，保留 BIND 配置文件"
fi

if [[ "${REMOVE_DATA}" == "yes" ]]; then
    log "删除 /var/named 数据目录"

    rm -rf /var/named
else
    warn "REMOVE_DATA=no，保留 /var/named，避免误删 DNS 区域数据"
fi

if [[ "${REMOVE_LOG}" == "yes" ]]; then
    log "删除 /var/log/named 日志目录"

    rm -rf /var/log/named
else
    warn "REMOVE_LOG=no，保留 /var/log/named"
fi

log "删除运行时目录"

rm -rf /run/named

log "清理 systemd 状态"

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

log "恢复 SELinux 上下文"

restorecon -Rv /etc /var 2>/dev/null || true

echo
echo "========== 卸载结果检查 =========="

echo
echo "1. RPM 包检查："
if rpm -qa | grep -E '^bind|^python3-bind' >/dev/null 2>&1; then
    warn "仍发现 BIND 相关 RPM 包："
    rpm -qa | grep -E '^bind|^python3-bind'
else
    echo "未发现 BIND 相关 RPM 包"
fi

echo
echo "2. named 命令检查："
if command -v named >/dev/null 2>&1; then
    warn "named 命令仍存在：$(command -v named)"
    named -v || true
else
    echo "named 命令已不存在"
fi

echo
echo "3. named 服务检查："
systemctl status named --no-pager 2>/dev/null || echo "named 服务已不存在或未加载"

echo
echo "4. 53 端口检查："
ss -lntup | grep ':53' || echo "当前未发现 53 端口监听"

echo
log "BIND 卸载完成"
echo "备份目录：${BACKUP_DIR}"
echo "REMOVE_PACKAGES=${REMOVE_PACKAGES}"
echo "REMOVE_CONFIG=${REMOVE_CONFIG}"
echo "REMOVE_DATA=${REMOVE_DATA}"
echo "REMOVE_LOG=${REMOVE_LOG}"
echo "REMOVE_SYSTEMD_UNIT=${REMOVE_SYSTEMD_UNIT}"
echo "REMOVE_FIREWALL=${REMOVE_FIREWALL}"