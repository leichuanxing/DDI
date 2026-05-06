"""网络探测类异步任务执行逻辑（由 Celery execute_system_task 调用）。"""
from __future__ import annotations

import ipaddress
import re
import socket
import time

import paramiko

from ipam.models import Subnet
from ipam.services import NetworkScanService

# 容器内常无 CAP_NET_RAW，ICMP 会报 Operation not permitted；此时回退 TCP 探测
TCP_FALLBACK_PORTS = (22, 80, 443, 445, 3389)
_ICMP_BLOCKED_HINTS = (
    "operation not permitted",
    "permission denied",
    "cap_net_raw",
    "required capability",
    "socket: operation not permitted",
    "cannot create icmp",
)

NETWORK_PROBE_TASK_TYPES = (
    ("network_ping_scan", "Ping 扫描"),
    ("network_port_scan", "端口扫描"),
    ("network_switch_arp", "交换机 ARP 获取"),
)
NETWORK_PROBE_TASK_LABELS = dict(NETWORK_PROBE_TASK_TYPES)
NETWORK_PROBE_TASK_TYPE_SET = frozenset(NETWORK_PROBE_TASK_LABELS.keys())

SENSITIVE_PAYLOAD_KEYS = frozenset({"ssh_password"})

MAX_SUBNET_PING_HOSTS = 254
MAX_PORT_SCAN_COUNT = 128


def redact_sensitive_payload(payload: dict | None) -> dict:
    """用于任务日志、详情页展示：脱敏敏感字段（执行仍使用原始 request_payload）。"""
    if not payload:
        return {}
    out = dict(payload)
    for key in SENSITIVE_PAYLOAD_KEYS:
        if out.get(key):
            out[key] = "***"
    return out


def _tcp_reachability_probe(ip: str) -> dict | None:
    """任一端口能建立 TCP 连接则视为在线（非 ICMP）。"""
    for port in TCP_FALLBACK_PORTS:
        t0 = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.2)
        try:
            sock.connect((ip, port))
            sock.close()
            ms = max(1, int((time.perf_counter() - t0) * 1000))
            return {
                "status": "online",
                "response_time": f"{ms} ms",
                "error_message": "",
                "probe_method": "tcp",
                "probe_detail": f"TCP {port} 可达（当前环境未使用 ICMP）",
            }
        except OSError:
            try:
                sock.close()
            except OSError:
                pass
    return None


def probe_host_reachability(ip: str) -> dict:
    """优先系统 ping；若因权限无法发 ICMP，则尝试常用 TCP 端口。"""
    r = NetworkScanService.ping(ip)
    if r.get("status") == "online":
        return r
    blob = f"{r.get('raw', '')}\n{r.get('error_message', '')}".lower()
    if any(h in blob for h in _ICMP_BLOCKED_HINTS):
        tcp_r = _tcp_reachability_probe(ip)
        if tcp_r:
            return tcp_r
        return {
            **r,
            "probe_method": "tcp",
            "probe_detail": "ICMP 不可用且 TCP 常用端口均无响应",
        }
    return r


def run_network_probe_task(task_type: str, payload: dict) -> dict:
    if task_type == "network_ping_scan":
        return run_ping_scan(payload)
    if task_type == "network_port_scan":
        return run_port_scan(payload)
    if task_type == "network_switch_arp":
        return run_switch_arp_scan(payload)
    return {"success": False, "message": f"未知探测任务: {task_type}", "data": {}}


def run_ping_scan(payload: dict) -> dict:
    mode = (payload.get("mode") or "single").strip()
    if mode == "single":
        ip = (payload.get("ip") or "").strip()
        if not ip:
            return {"success": False, "message": "请填写要 Ping 的 IP 地址", "data": {}}
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return {"success": False, "message": "IP 地址格式不正确", "data": {}}
        r = probe_host_reachability(ip)
        return {
            "success": True,
            "message": "单地址探测完成",
            "data": {"mode": "single", "results": [{"ip": ip, **r}]},
        }

    if mode == "subnet":
        sid = payload.get("subnet_id")
        if not sid:
            return {"success": False, "message": "请选择子网", "data": {}}
        try:
            subnet = Subnet.objects.get(pk=sid)
        except Subnet.DoesNotExist:
            return {"success": False, "message": "子网不存在", "data": {}}
        hosts = list(subnet.network.hosts())
        if len(hosts) > MAX_SUBNET_PING_HOSTS:
            return {
                "success": False,
                "message": f"子网主机位超过 {MAX_SUBNET_PING_HOSTS}，请缩小网段后重试",
                "data": {},
            }
        results = []
        for h in hosts:
            ip = str(h)
            row = probe_host_reachability(ip)
            results.append({"ip": ip, **row})
        return {
            "success": True,
            "message": f"已对子网 {subnet.cidr} 内 {len(results)} 个地址执行 Ping",
            "data": {
                "mode": "subnet",
                "subnet_id": subnet.id,
                "subnet_cidr": subnet.cidr,
                "results": results,
            },
        }

    return {"success": False, "message": "不支持的 Ping 模式", "data": {}}


def _parse_ports(spec: str) -> list[int]:
    ports: set[int] = set()
    for part in spec.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a.strip()), int(b.strip())
                if lo > hi:
                    lo, hi = hi, lo
                for p in range(lo, hi + 1):
                    if 1 <= p <= 65535:
                        ports.add(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= 65535:
                    ports.add(p)
            except ValueError:
                continue
    return sorted(ports)


def _tcp_probe(host: str, port: int, timeout: float = 1.0) -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.close()
        return True, "open"
    except socket.timeout:
        return False, "timeout"
    except OSError as exc:
        return False, str(exc)[:120]


def run_port_scan(payload: dict) -> dict:
    host = (payload.get("host") or "").strip()
    ports_spec = (payload.get("ports") or "22,80,443").strip()
    if not host:
        return {"success": False, "message": "请填写目标 IP", "data": {}}
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return {"success": False, "message": "目标 IP 格式不正确", "data": {}}
    ports = _parse_ports(ports_spec)
    if not ports:
        return {"success": False, "message": "请填写有效端口（如 22,80 或 1-1024）", "data": {}}
    if len(ports) > MAX_PORT_SCAN_COUNT:
        return {
            "success": False,
            "message": f"单次最多扫描 {MAX_PORT_SCAN_COUNT} 个端口",
            "data": {},
        }
    results = []
    open_count = 0
    for port in ports:
        ok, detail = _tcp_probe(host, port)
        if ok:
            open_count += 1
        results.append({"port": port, "open": ok, "detail": detail})
    return {
        "success": True,
        "message": f"端口扫描完成，开放 {open_count}/{len(ports)}",
        "data": {"host": host, "ports_requested": ports_spec, "results": results},
    }


def _mac_from_token(raw: str) -> str | None:
    hx = re.sub(r"[^0-9a-fA-F]", "", raw)
    if len(hx) != 12:
        return None
    return ":".join(hx[i : i + 2].lower() for i in range(0, 12, 2))


def _valid_arp_entry(ip: str, mac: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    if addr.is_multicast:
        return False
    if mac == "00:00:00:00:00:00":
        return False
    first = int(mac.split(":", 1)[0], 16)
    if first & 1:
        return False
    return True


def _parse_cli_arp_output(text: str) -> list[dict]:
    """从 CLI 输出中尽力提取 IPv4 + MAC（Cisco / Linux arp / ip neigh / 华三等常见行）。"""
    rows: dict[str, dict] = {}
    patterns = (
        re.compile(
            r"\((?P<ip>\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+(?P<mac>[0-9a-fA-F:.]+?)(?:\s+|\[|$)",
            re.I,
        ),
        re.compile(
            r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+.*?\blladdr\s+(?P<mac>[0-9a-fA-F:]+)\b",
            re.I,
        ),
        re.compile(
            r"Internet\s+(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+\S+\s+"
            r"(?P<mac>(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4}|(?:[0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2})\s",
            re.I,
        ),
        re.compile(
            r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+"
            r"(?P<mac>(?:[0-9a-fA-F]{4}-){2}[0-9a-fA-F]{4})(?:\s|$)",
            re.I,
        ),
        re.compile(
            r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+"
            r"(?P<mac>(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2})(?:\s|$)",
            re.I,
        ),
        re.compile(
            r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+"
            r"(?P<mac>(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4})(?:\s|$)",
            re.I,
        ),
    )
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        for pat in patterns:
            m = pat.search(line)
            if not m:
                continue
            ip_txt = m.group("ip")
            mac = _mac_from_token(m.group("mac"))
            if mac and _valid_arp_entry(ip_txt, mac):
                rows[ip_txt] = {"ip": ip_txt, "mac": mac}
            break
    return list(rows.values())


def _ssh_exec_with_optional_pty(client: paramiko.SSHClient, cmd: str) -> tuple[bytes, bytes]:
    """在已连接的 client 上执行单条命令：先 PTY 再回退无 PTY。"""
    errors: list[BaseException] = []
    for use_pty in (True, False):
        try:
            _stdin, stdout, stderr = client.exec_command(cmd, timeout=120, get_pty=use_pty)
            out_b = stdout.read() or b""
            err_b = stderr.read() or b""
            try:
                stdout.channel.recv_exit_status()
            except Exception:
                pass
            return out_b, err_b
        except (paramiko.SSHException, OSError, socket.timeout, EOFError) as exc:
            errors.append(exc)
        except Exception as exc:
            errors.append(exc)
    raise errors[-1] if errors else RuntimeError("exec_command 失败")


def _sort_arp_entries(entries: list[dict]) -> list[dict]:
    def _key(row: dict) -> tuple:
        try:
            return (0, int(ipaddress.ip_address(row.get("ip") or "0.0.0.0")))
        except ValueError:
            return (1, 0)

    return sorted(entries, key=_key)


def run_switch_arp_scan(payload: dict) -> dict:
    switch_ip = (payload.get("switch_ip") or "").strip()
    username = (payload.get("ssh_username") or "").strip()
    password = payload.get("ssh_password") or ""
    commands_text = (payload.get("ssh_commands") or "").strip()
    port_raw = payload.get("ssh_port", 22)
    try:
        ssh_port = int(port_raw)
    except (TypeError, ValueError):
        ssh_port = 22
    if not (1 <= ssh_port <= 65535):
        ssh_port = 22

    if not switch_ip:
        return {"success": False, "message": "请填写交换机管理 IP", "data": {}}
    try:
        ipaddress.ip_address(switch_ip)
    except ValueError:
        return {"success": False, "message": "交换机 IP 格式不正确", "data": {}}
    if not username:
        if (payload.get("community") or "").strip():
            return {
                "success": False,
                "message": "当前 ARP 探测已改为 SSH：请重新提交任务并填写 SSH 用户名、密码与远程命令（旧版仅 SNMP 团体字的参数已不再使用）。",
                "data": {},
            }
        return {"success": False, "message": "请填写 SSH 用户名", "data": {}}
    command_lines = [ln.strip() for ln in commands_text.splitlines() if ln.strip()]
    if not command_lines:
        return {"success": False, "message": "请填写至少一条远程命令", "data": {}}

    # 每条命令使用独立 SSH 连接。不少交换机在一次会话里只允许一条 exec，第二条会报「SSH session not active」。
    chunks: list[str] = []
    for cmd in command_lines:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            try:
                client.connect(
                    switch_ip,
                    port=ssh_port,
                    username=username,
                    password=password,
                    timeout=30,
                    banner_timeout=30,
                    auth_timeout=30,
                    allow_agent=False,
                    look_for_keys=False,
                )
            except paramiko.AuthenticationException:
                return {"success": False, "message": "SSH 认证失败（用户名或密码错误）", "data": {}}
            except (paramiko.SSHException, OSError, socket.timeout, EOFError) as exc:
                chunks.append(f"=== {cmd} ===\n<连接异常: {exc}>\n")
                continue
            except Exception as exc:
                chunks.append(f"=== {cmd} ===\n<连接异常 ({type(exc).__name__}): {exc}>\n")
                continue

            try:
                out_b, err_b = _ssh_exec_with_optional_pty(client, cmd)
            except BaseException as exc:
                chunks.append(f"=== {cmd} ===\n<执行异常 ({type(exc).__name__}): {exc}>\n")
            else:
                out = out_b.decode(errors="replace")
                err = err_b.decode(errors="replace")
                chunks.append(f"=== {cmd} ===\n{out}")
                if err.strip():
                    chunks.append(f"=== {cmd} (stderr) ===\n{err}")
        finally:
            client.close()

    full_text = "\n".join(chunks)
    entries = _sort_arp_entries(_parse_cli_arp_output(full_text))
    parsed_count = len(entries)
    has_exec_error = "<执行异常" in full_text or "<连接异常" in full_text

    if has_exec_error and parsed_count == 0:
        return {
            "success": False,
            "message": "远程命令未全部成功执行或输出无法解析（常见原因为设备限制单次 SSH 会话仅一条命令；本系统已按命令分别建连，若仍失败请检查账号、权限与命令是否正确）。",
            "data": {
                "switch_ip": switch_ip,
                "ssh_port": ssh_port,
                "entries": [],
                "raw_stdout": full_text[:12000],
                "parsed_count": 0,
            },
        }

    msg = f"已解析 {parsed_count} 条 IPv4/MAC 记录"
    if has_exec_error and parsed_count > 0:
        msg += "（部分命令执行异常，结果可能不完整，请展开原始输出核对）"

    return {
        "success": True,
        "message": msg,
        "data": {
            "switch_ip": switch_ip,
            "ssh_port": ssh_port,
            "entries": entries,
            "raw_stdout": full_text[:12000],
            "parsed_count": parsed_count,
        },
    }
