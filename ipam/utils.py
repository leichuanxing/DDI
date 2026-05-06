import re


MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


STATUS_LABELS = {
    "available": "空闲",
    "used": "已使用",
    "gateway": "网关",
    "disabled": "禁用",
    "reserved": "预留",
    "dhcp_dynamic": "DHCP 动态分配",
    "dhcp_reserved": "DHCP 固定分配",
    "online": "在线",
    "offline": "离线",
    "unknown": "未知",
}


def normalize_mac(value):
    value = (value or "").strip().replace("-", ":").lower()
    return value


def validate_mac(value):
    if not value:
        return True
    return bool(MAC_RE.match(normalize_mac(value)))


def utilization_class(value):
    if value >= 90:
        return "danger"
    if value >= 70:
        return "warn"
    return ""
