#!/bin/bash
# ============================================================
#  DDI 管理系统 - 停止脚本
#  用法: ./stop.sh [-k|--kill] [--port PORT]
#
#  选项:
#    -k, --kill   - 强制杀死进程 (SIGKILL)
#    --port PORT   - 指定端口 (默认 8000)
# ============================================================

set -e

# ==================== 全局配置 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/ddi.pid"
APP_NAME="ddi_system"
PORT="8000"
FORCE_KILL=false

# 解析参数
for arg in "$@"; do
    case "$arg" in
        -k|--kill)     FORCE_KILL=true ;;
        --port)        shift; PORT="${1:-8000}" ;;
        -h|--help)
            echo "用法: $0 [-k|--kill] [--port PORT]"
            echo ""
            echo "  -k, --kill  强制杀死进程"
            echo "  --port N    指定端口 (默认 8000)"
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

log_info()  { echo -e "${CYAN}[信息]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[成功]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[警告]${NC} $1"; }
log_error() { echo -e "${RED}[错误]${NC} $1"; }

# ==================== 停止函数 ====================
# 方式1: 通过 PID 文件停止
stop_by_pid() {
    local pid=$1
    log_info "通过 PID 文件停止 (PID: $pid)..."

    send_signal "$pid"
    rm -f "$PID_FILE"
}

# 方式2: 通过进程名/端口查找并停止
stop_by_name() {
    local pids=""
    local found=0

    # 查找 Gunicorn master 进程
    pids=$(pgrep -f "gunicorn.*ddi_system.wsgi" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        found=1
        for pid in $pids; do
            # 只杀 master（父进程是自己或 init 的）
            local ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
            if [ "$ppid" = "1" ] || [ -z "$(ps -o ppid= -p "$ppid" 2>/dev/null)" ] 2>/dev/null; then
                log_info "找到 Gunicorn master (PID: $pid)，正在停止..."
                send_signal "$pid"
                found=1
            fi
        done
        # 兜底：杀所有 gunicorn worker
        if [ "$FORCE_KILL" = true ]; then
            pkill -9 -f "gunicorn.*ddi_system.wsgi" 2>/dev/null || true
        else
            pkill -f "gunicorn.*ddi_system.wsgi" 2>/dev/null || true
        fi
    fi

    # 查找 Django dev server (runserver)
    pids=$(pgrep -f "manage.py.*runserver" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        found=1
        for pid in $pids; do
            log_info "找到开发服务器 (PID: $pid)，正在停止..."
            send_signal "$pid"
        done
    fi

    # 查找占用端口的进程（兜底）
    if [ "$found" -eq 0 ]; then
        local port_pids=""
        if command -v ss &>/dev/null; then
            port_pids=$(ss -tlnp sport = :$PORT 2>/dev/null | grep -oP 'pid=\K\d+' || true)
        elif command -v lsof &>/dev/null; then
            port_pids=$(lsof -ti:$PORT 2>/dev/null || true)
        fi
        if [ -n "$port_pids" ]; then
            for pid in $port_pids; do
                log_info "找到占用端口 ${PORT} 的进程 (PID: $pid)，正在停止..."
                send_signal "$pid"
            done
        else
            log_warn "未找到运行中的服务"
            return 0
        fi
    fi

    rm -f "$PID_FILE"
}

# 发送信号并等待退出
send_signal() {
    local pid=$1

    if [ "$FORCE_KILL" = true ]; then
        kill -9 "$pid" 2>/dev/null && return 0
    fi

    kill "$pid" 2>/dev/null || return 0

    # 等待优雅退出，最多 10 秒
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$i" -ge 10 ]; then
            log_warn "进程未响应，强制终止..."
            kill -9 "$pid" 2>/dev/null
            break
        fi
        sleep 1
        i=$((i + 1))
    done
}

# ==================== 主流程 ====================
main() {
    echo ""
    echo -e "${BOLD}${GREEN}============================================${NC}"
    echo -e "${BOLD}${GREEN}   DDI 管理系统 - 停止服务${NC}"
    echo -e "${BOLD}${GREEN}============================================${NC}"
    echo ""

    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            stop_by_pid "$pid"
        else
            log_warn "PID 文件存在但进程不存在 (PID: $pid)，按名称查找..."
            rm -f "$PID_FILE"
            stop_by_name
        fi
    else
        stop_by_name
    fi

    log_ok "服务已停止"
}

main "$@"
