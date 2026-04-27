
#!/usr/bin/env bash
set -euo pipefail

# ==============================
# BIND9 卸载脚本
# 适用系统：Red Hat 9 / Rocky Linux 9 / AlmaLinux 9
# ==============================

# 是否删除配置文件
# yes：删除 /etc/named.conf、/etc/named.rfc1912.zones、/etc/named.root.key 等
# no ：仅备份，不删除
REMOVE_CONFIG="${REMOVE_CONFIG:-yes}"

# 是否删除 /var/named 数据目录
# 生产环境建议保持 no，避免误删 zone 文件
REMOVE_DATA="${REMOVE_DATA:-no}"

# 是否删除 named 日志目录
REMOVE_LOG="${REMOVE_LOG:-yes}"

# 是否移除防火墙 DNS 放行
REMOVE_FIREWALL="${REMOVE_FIREWALL:-yes}"

# 是否移除 versionlock 锁定
REMOVE_VERSIONLOCK="${REMOVE_VERSIONLOCK:-yes}"

BACKUP_DIR="/root/named_uninstall_backup_$(date +%F_%H%M%S)"

log() {
    echo -e "\033[1;32m[$(date '+%F %T')] $*\033[0m"
}

warn() {
    echo -e "\033[1;33m[WARN] $*\033[0m"
}

die() {
    echo -e "\033[1;31m[ERROR] $*\033[0m" >&2
    exit 1
}

if [[ "$EUID" -ne 0 ]]; then
    die "请使用 root 用户执行本脚本。"
fi

if [[ ! -f /etc/os-release ]]; then
    die "无法识别系统版本，未找到 /etc/os-release。"
fi

. /etc/os-release

OS_MAJOR="${VERSION_ID%%.*}"

if [[ "$OS_MAJOR" != "9" ]]; then
    warn "当前系统不是 9 系版本：${PRETTY_NAME:-unknown}，请确认后继续。"
fi

log "当前系统：${PRETTY_NAME:-unknown}"

log "创建备份目录：${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"

log "备份 BIND 配置和数据"

for file in \
    /etc/named.conf \
    /etc/named.rfc1912.zones \
    /etc/named.root.key \
    /etc/rndc.conf \
    /etc/rndc.key
do
    if [[ -e "$file" ]]; then
        cp -a "$file" "${BACKUP_DIR}/"
        log "已备份：$file"
    fi
done

for dir in \
    /var/named \
    /var/log/named \
    /run/named
do
    if [[ -e "$dir" ]]; then
        cp -a "$dir" "${BACKUP_DIR}/" 2>/dev/null || true
        log "已备份目录：$dir"
    fi
done

log "停止 named 服务"

if systemctl list-unit-files | grep -q '^named.service'; then
    systemctl stop named 2>/dev/null || true
    systemctl disable named 2>/dev/null || true
    systemctl reset-failed named 2>/dev/null || true
else
    warn "未发现 named.service，跳过服务停止。"
fi

log "检查 named 相关进程"

if pgrep -x named >/dev/null 2>&1; then
    warn "发现 named 进程仍在运行，尝试终止。"
    pkill -x named || true
    sleep 2

    if pgrep -x named >/dev/null 2>&1; then
        warn "named 进程仍未退出，强制终止。"
        pkill -9 -x named || true
    fi
fi

if [[ "${REMOVE_FIREWALL}" == "yes" ]]; then
    log "处理防火墙 DNS 服务放行"

    if systemctl is-active --quiet firewalld; then
        firewall-cmd --permanent --remove-service=dns 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
        log "已移除 firewalld 中的 dns 服务放行。"
    else
        warn "firewalld 未运行，跳过防火墙处理。"
    fi
fi

if [[ "${REMOVE_VERSIONLOCK}" == "yes" ]]; then
    log "尝试移除 BIND versionlock 锁定"

    if command -v dnf >/dev/null 2>&1 && dnf versionlock list >/dev/null 2>&1; then
        dnf versionlock delete bind bind-utils bind-libs bind-dnssec-utils bind-license 2>/dev/null || true
    else
        warn "versionlock 插件不可用或未启用，跳过。"
    fi
fi

log "卸载 BIND 相关软件包"

dnf remove -y \
    bind \
    bind-utils \
    bind-libs \
    bind-license \
    bind-dnssec-utils \
    python3-bind \
    bind-chroot \
    bind-devel \
    2>/dev/null || true

log "检查残留 RPM 包"

rpm -qa | grep -E '^bind|^python3-bind' || true

if [[ "${REMOVE_CONFIG}" == "yes" ]]; then
    log "删除 BIND 配置文件"

    rm -f /etc/named.conf
    rm -f /etc/named.rfc1912.zones
    rm -f /etc/named.root.key
    rm -f /etc/rndc.conf
    rm -f /etc/rndc.key

    rm -rf /etc/named
    rm -rf /etc/named.*
else
    warn "REMOVE_CONFIG=no，已保留 BIND 配置文件。"
fi

if [[ "${REMOVE_DATA}" == "yes" ]]; then
    log "删除 /var/named 数据目录"

    rm -rf /var/named
else
    warn "REMOVE_DATA=no，已保留 /var/named 数据目录。"
fi

if [[ "${REMOVE_LOG}" == "yes" ]]; then
    log "删除 named 日志目录"

    rm -rf /var/log/named
fi

log "删除运行时目录"

rm -rf /run/named

log "刷新 systemd 状态"

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

log "验证卸载结果"

if command -v named >/dev/null 2>&1; then
    warn "named 命令仍存在：$(command -v named)"
    named -v || true
else
    log "named 命令已不存在。"
fi

if rpm -qa | grep -E '^bind|^python3-bind' >/dev/null 2>&1; then
    warn "仍存在 BIND 相关 RPM 包："
    rpm -qa | grep -E '^bind|^python3-bind'
else
    log "BIND 相关 RPM 包已卸载完成。"
fi

echo
log "BIND9 卸载完成"
echo "备份目录：${BACKUP_DIR}"
echo "是否删除配置文件 REMOVE_CONFIG=${REMOVE_CONFIG}"
echo "是否删除数据目录 REMOVE_DATA=${REMOVE_DATA}"
echo "是否删除日志目录 REMOVE_LOG=${REMOVE_LOG}"