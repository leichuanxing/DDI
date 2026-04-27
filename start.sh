#!/bin/bash
# ============================================================
#  DDI 管理系统 - 启动脚本
#  用法: ./start.sh [dev|prod] [--port PORT] [--bind HOST]
#
#  模式:
#    dev   - 开发模式 (Django runserver, 默认, 前台运行)
#    prod  - 生产模式 (Gunicorn, 后台运行)
#
#  选项:
#    --port PORT   - 指定端口 (默认 8000)
#    --bind HOST   - 绑定地址 (默认 0.0.0.0)
# ============================================================

set -e

# ==================== 全局配置 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="ddi_system"
PID_FILE="$SCRIPT_DIR/ddi.pid"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/ddi.log"
HOST="0.0.0.0"
PORT="8000"
WORKERS=4
TIMEOUT=120
MODE="dev"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

# 解析参数
for arg in "$@"; do
    case "$arg" in
        dev|prod)    MODE="$arg" ;;
        --port)      shift; PORT="${1:-8000}" ;;
        --bind)      shift; HOST="${1:-0.0.0.0}" ;;
        -h|--help)
            echo "用法: $0 [dev|prod] [--port PORT] [--bind HOST]"
            echo ""
            echo "  dev       开发模式 (默认, Django runserver)"
            echo "  prod      生产模式 (Gunicorn 后台运行)"
            echo "  --port N  端口 (默认 8000)"
            echo "  --bind A  绑定地址 (默认 0.0.0.0)"
            exit 0
            ;;
    esac
done

# ==================== 工具函数 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${CYAN}[信息]${NC} $1"; }
log_ok()      { echo -e "${GREEN}[成功]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[警告]${NC} $1"; }
log_error()   { echo -e "${RED}[错误]${NC} $1"; }

die() {
    log_error "$1"
    exit 1
}

# ==================== 环境检查 ====================
check_python() {
    if ! command -v python3 &>/dev/null; then
        die "未找到 python3，请先安装 Python 3.8+"
    fi

    local py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major=$(echo "$py_ver" | cut -d. -f1)
    local minor=$(echo "$py_ver" | cut -d. -f2)

    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 8 ]; }; then
        die "Python 版本过低 ($py_ver)，需要 >= 3.8"
    fi

    log_ok "Python $py_ver"
}

install_deps() {
    if ! pip install -r "$REQUIREMENTS_FILE" -q 2>&1; then
        die "依赖安装失败，请检查 $REQUIREMENTS_FILE 和网络连接"
    fi
    log_ok "依赖已就绪"
}

collect_static() {
    log_info "收集静态文件..."
    python manage.py collectstatic --noinput 2>&1 | tail -1 || true
}

run_migrations() {
    log_info "执行数据库迁移..."
    python manage.py migrate --no-input 2>&1 | grep -E "(OK|Running)" || true
}

check_port() {
    if command -v ss &>/dev/null; then
        if ss -tlnp 2>/dev/null | grep -qw ":${PORT}\b"; then
            die "端口 ${PORT} 已被占用，请释放后重试或使用 --port 切换端口"
        fi
    elif command -v netstat &>/dev/null; then
        if netstat -tlnp 2>/dev/null | grep -qw ":${PORT}"; then
            die "端口 ${PORT} 已被占用，请释放后重试或使用 --port 切换端口"
        fi
    fi
}

check_bind9() {
    local named_bin="/usr/sbin/named"
    export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH"
    if [ -x "$named_bin" ] && pgrep -x named &>/dev/null; then
        log_ok "BIND9 服务运行中"
    else
        log_warn "BIND9 未运行或未安装，DNS 发布功能将不可用"
        log_warn "  如需使用 DNS 管理，请先执行: sudo ./install_bind9.sh"
    fi
}

check_init_data() {
    # 检查是否有基础数据，避免首次启动时数据库为空
    if python manage.py shell -c "
from django.contrib.auth.models import User;
exit(0 if User.objects.exists() else 1)
" 2>/dev/null; then
        :
    else
        log_warn "检测到空数据库，正在初始化数据..."
        python init_data.py 2>&1 | head -5
        log_ok "初始数据已加载"
    fi
}

cleanup_stale_pid() {
    if [ -f "$PID_FILE" ]; then
        local old_pid=$(cat "$PID_FILE")
        if kill -0 "$old_pid" 2>/dev/null; then
            die "应用已在运行 (PID: $old_pid)，请先执行: ./stop.sh"
        else
            log_warn "清理残留 PID 文件 ($old_pid)"
            rm -f "$PID_FILE"
        fi
    fi
}

# ==================== 主流程 ====================
main() {
    echo ""
    echo -e "${BOLD}${GREEN}============================================${NC}"
    echo -e "${BOLD}${GREEN}   DDI 管理系统 启动器${NC}"
    echo -e "${BOLD}${GREEN}============================================${NC}"
    echo ""

    # 1) 环境检查
    log_info "环境自检..."
    check_python
    install_deps

    # 2) 进程与端口检查
    cleanup_stale_pid
    check_port

    # 3) 数据库准备
    run_migrations
    check_init_data
    collect_static

    # 4) 外部服务检查
    check_bind9

    mkdir -p "$LOG_DIR"

    # ==================== 启动服务 ====================
    case "$MODE" in
        dev)
            echo ""
            echo -e "${GREEN}============================================${NC}"
            echo -e "${GREEN}   模式: ${BOLD}开发服务器 (Django)${NC}"
            echo -e "${GREEN}============================================${NC}"
            echo -e "  地址: ${CYAN}http://${HOST}:${PORT}${NC}"
            echo -e "  日志: 控制台输出"
            echo -e "${GREEN}============================================${NC}"
            echo -e "  按 ${YELLOW}Ctrl+C${NC} 停止服务"
            echo ""

            exec python manage.py runserver ${HOST}:${PORT}
            ;;

        prod)
            echo ""
            echo -e "${GREEN}============================================${NC}"
            echo -e "${GREEN}   模式: ${BOLD}生产服务器 (Gunicorn)${NC}"
            echo -e "${GREEN}============================================${NC}"
            echo -e "  地址: ${CYAN}http://${HOST}:${PORT}${NC}"
            echo -e "  Worker: ${WORKERS} 进程 x 4 线程"
            echo -e "  日志: ${CYAN}$LOG_FILE${NC}"
            echo -e "  PID:  ${CYAN}$PID_FILE${NC}"
            echo -e "${GREEN}============================================${NC}"
            echo -e "  执行 ${YELLOW}./stop.sh${NC} 停止服务"
            echo ""

            # 注意: 不能用 exec + --daemon 组合，exec 会替换进程导致 daemon 无法后台运行
            gunicorn \
                --bind ${HOST}:${PORT} \
                --workers $WORKERS \
                --worker-class gthread \
                --threads 4 \
                --timeout $TIMEOUT \
                --keep-alive 5 \
                --max-requests 1000 \
                --max-requests-jitter 50 \
                --access-logfile "$LOG_FILE" \
                --error-logfile "$LOG_FILE" \
                --pid "$PID_FILE" \
                --daemon \
                ddi_system.wsgi:application

            sleep 1.5

            # 验证启动结果
            if [ -f "$PID_FILE" ]; then
                local pid=$(cat "$PID_FILE")
                if kill -0 "$pid" 2>/dev/null; then
                    log_ok "服务已启动 (PID: $pid)"
                    log_info "查看日志: tail -f $LOG_FILE"
                else
                    die "进程启动失败，请查看日志: $LOG_FILE"
                fi
            else
                die "PID 文件未生成，Gunicorn 可能未能正常启动"
            fi
            ;;

        *)
            die "未知模式: '$MODE'，支持: dev / prod"
            ;;
    esac
}

main "$@"
