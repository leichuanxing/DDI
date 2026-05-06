import ipaddress
import platform
import subprocess
import time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import IPAddress, IPAddressHistory, NetworkScanRecord, Subnet

# 子网详情「全量主机位」清单：超过则仅展示已入库记录（避免超大网段拖垮内存）
MAX_MERGED_SUBNET_HOSTS = 65536


class SubnetIPGridRow:
    """网段内单个主机位展示行：可无 IPAddress 库记录（虚拟空闲）。"""

    __slots__ = ("subnet", "ip_address", "_rec")

    def __init__(self, subnet, ip_address, record=None):
        self.subnet = subnet
        self.ip_address = ip_address
        self._rec = record

    @property
    def pk(self):
        return self._rec.pk if self._rec else None

    @property
    def status(self):
        return self._rec.status if self._rec else "available"

    def get_status_display(self):
        if self._rec:
            return self._rec.get_status_display()
        return "空闲（未入库）"

    @property
    def hostname(self):
        return self._rec.hostname if self._rec else None

    @property
    def device_name(self):
        return self._rec.device_name if self._rec else None

    @property
    def owner(self):
        return self._rec.owner if self._rec else None

    @property
    def mac_address(self):
        return self._rec.mac_address if self._rec else None

    @property
    def bind_type(self):
        return self._rec.bind_type if self._rec else None

    def get_bind_type_display(self):
        if self._rec and self._rec.bind_type:
            return self._rec.get_bind_type_display()
        return ""

    @property
    def last_scan_time(self):
        return self._rec.last_scan_time if self._rec else None

    @property
    def description(self):
        return self._rec.description if self._rec else None

    @property
    def has_db_record(self):
        return self._rec is not None


class MergedSubnetIPPage:
    """与 Django Page 常用属性对齐，供子网详情模板分页使用。"""

    def __init__(self, object_list, number, per_page, total_count):
        self.object_list = object_list
        self.number = number
        total = int(total_count)
        per_page = max(1, int(per_page))
        num_pages = max(1, (total + per_page - 1) // per_page) if total else 1
        self.paginator = type(
            "PaginatorShim",
            (),
            {"count": total, "per_page": per_page, "num_pages": num_pages},
        )()

    @property
    def start_index(self):
        if not self.paginator.count:
            return None
        return (self.number - 1) * self.paginator.per_page + 1

    @property
    def end_index(self):
        if not self.paginator.count:
            return None
        return (self.number - 1) * self.paginator.per_page + len(self.object_list)

    def has_other_pages(self):
        return self.paginator.num_pages > 1

    def has_previous(self):
        return self.number > 1

    def has_next(self):
        return self.number < self.paginator.num_pages

    def previous_page_number(self):
        return self.number - 1

    def next_page_number(self):
        return self.number + 1


class SubnetService:
    MAX_MERGED_SUBNET_HOSTS = MAX_MERGED_SUBNET_HOSTS

    @staticmethod
    def calculate_subnet_info(cidr):
        network = ipaddress.ip_network(cidr, strict=False)
        total_ips = max(network.num_addresses - 2, 0)
        return {
            "network": network,
            "network_address": str(network.network_address),
            "broadcast_address": str(network.broadcast_address) if network.version == 4 else "",
            "netmask": str(network.netmask),
            "total_ips": total_ips,
        }

    @staticmethod
    def check_subnet_overlap(cidr, exclude_id=None):
        current = ipaddress.ip_network(cidr, strict=False)
        queryset = Subnet.objects.exclude(pk=exclude_id)
        for subnet in queryset.only("id", "cidr"):
            try:
                if current.overlaps(ipaddress.ip_network(subnet.cidr, strict=False)):
                    return subnet
            except ValueError:
                continue
        return None

    @staticmethod
    @transaction.atomic
    def generate_ips(subnet):
        subnet.full_clean()
        subnet.save()

        created = 0
        updated = 0
        network = subnet.network
        gateway_ip = str(subnet.gateway) if subnet.gateway else ""
        network_ip = str(network.network_address)
        broadcast_ip = str(network.broadcast_address) if network.version == 4 else ""

        for host in network.hosts():
            ip_text = str(host)
            defaults = {
                "status": "gateway" if gateway_ip and ip_text == gateway_ip else "available",
                "bind_type": "manual" if gateway_ip and ip_text == gateway_ip else None,
            }
            ip_obj, was_created = IPAddress.objects.get_or_create(
                subnet=subnet,
                ip_address=ip_text,
                defaults=defaults,
            )
            if was_created:
                created += 1
            elif ip_text == gateway_ip and ip_obj.status != "gateway":
                ip_obj.status = "gateway"
                ip_obj.bind_type = "manual"
                ip_obj.save(update_fields=["status", "bind_type", "updated_at"])
                updated += 1

        IPAddress.objects.filter(subnet=subnet, ip_address__in=[network_ip, broadcast_ip]).delete()
        SubnetService.recalculate_usage(subnet)
        return {
            "created": created,
            "updated": updated,
            "total": subnet.ip_addresses.count(),
        }

    @staticmethod
    def recalculate_usage(subnet):
        used_statuses = {"used", "gateway", "dhcp_dynamic", "dhcp_reserved", "reserved"}
        subnet.used_ips = subnet.ip_addresses.filter(status__in=used_statuses).count()
        subnet.total_ips = max(subnet.network.num_addresses - 2, 0)
        subnet.save(update_fields=["used_ips", "total_ips", "updated_at"])
        return subnet

    @staticmethod
    def ip_status_breakdown(subnet):
        rows = subnet.ip_addresses.values("status").annotate(c=Count("id"))
        counts = {row["status"]: row["c"] for row in rows}
        for code, _ in IPAddress.STATUS_CHOICES:
            counts.setdefault(code, 0)
        return counts

    @staticmethod
    def host_addresses_enumerated_flat(subnet):
        """
        按 CIDR 枚举全部可主机地址（字符串）。
        若主机位数超过 MAX_MERGED_SUBNET_HOSTS 则返回 None，由页面降级为仅展示已入库记录。
        """
        out = []
        for host in subnet.network.hosts():
            out.append(str(host))
            if len(out) > SubnetService.MAX_MERGED_SUBNET_HOSTS:
                return None
        return tuple(out)

    @staticmethod
    def paginate_merged_subnet_ip_page(subnet, host_ips, page_raw, per_page):
        """将枚举主机位与库内 IPAddress 合并后分页。"""
        total = len(host_ips)
        if total == 0:
            return MergedSubnetIPPage([], 1, per_page, 0)

        try:
            page_num = int(page_raw)
        except (TypeError, ValueError):
            page_num = 1
        per_page = max(1, int(per_page))
        num_pages = max(1, (total + per_page - 1) // per_page)
        page_num = max(1, min(page_num, num_pages))

        start = (page_num - 1) * per_page
        chunk = host_ips[start : start + per_page]

        db_map = {
            str(ip.ip_address): ip
            for ip in IPAddress.objects.filter(subnet=subnet, ip_address__in=chunk)
        }
        rows = [SubnetIPGridRow(subnet, ip_s, db_map.get(ip_s)) for ip_s in chunk]
        return MergedSubnetIPPage(rows, page_num, per_page, total)


class NetworkScanService:
    @staticmethod
    def _ping_command(ip_address):
        if platform.system().lower().startswith("win"):
            return ["ping", "-n", "1", "-w", "1000", ip_address]
        return ["ping", "-c", "1", "-W", "1", ip_address]

    @staticmethod
    def ping(ip_address):
        ip_obj = ipaddress.ip_address(str(ip_address).strip())
        command = NetworkScanService._ping_command(str(ip_obj))
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
        except subprocess.TimeoutExpired:
            return {
                "status": "offline",
                "response_time": "-",
                "error_message": "Ping 超时",
            }
        output = f"{result.stdout}\n{result.stderr}".strip()
        if result.returncode == 0:
            return {
                "status": "online",
                "response_time": f"{duration_ms} ms",
                "error_message": "",
                "raw": output,
            }
        return {
            "status": "offline",
            "response_time": "-",
            "error_message": output.splitlines()[-1][:255] if output else "Ping 失败",
            "raw": output,
        }

    @staticmethod
    @transaction.atomic
    def scan_subnet(subnet):
        hosts = list(subnet.ip_addresses.order_by("ip_address")[:254])
        if len(hosts) > 254:
            raise ValidationError("批量探测一次最多 254 个 IP。")
        records = []
        for ip_obj in hosts:
            result = NetworkScanService.ping(ip_obj.ip_address)
            ip_obj.last_scan_status = result["status"]
            ip_obj.last_scan_time = timezone.now()
            ip_obj.save(update_fields=["last_scan_status", "last_scan_time", "updated_at"])
            records.append(
                NetworkScanRecord.objects.create(
                    ip_address=ip_obj.ip_address,
                    subnet=subnet,
                    status=result["status"],
                    response_time=result.get("response_time", ""),
                    error_message=result.get("error_message", ""),
                )
            )
        return records


class IPAddressService:
    ALLOCATABLE_STATUSES = {"available", "reserved"}
    CLEAR_FIELDS = {
        "hostname": "",
        "device_name": "",
        "owner": "",
        "mac_address": "",
        "bind_type": "manual",
        "usage_type": "",
        "department": "",
        "description": "",
        "dns_record": None,
        "dhcp_reservation": None,
    }

    @staticmethod
    def _history(ip_obj, action, old_status, new_status, user=None, detail=None):
        IPAddressHistory.objects.create(
            ip_address=ip_obj,
            action=action,
            old_status=old_status,
            new_status=new_status,
            operator=user,
            detail=detail or {},
        )

    @staticmethod
    @transaction.atomic
    def set_status(ip_obj, status, user=None, action="status_change", **fields):
        old_status = ip_obj.status
        for key, value in fields.items():
            setattr(ip_obj, key, value)
        ip_obj.status = status
        ip_obj.full_clean()
        ip_obj.save()
        IPAddressService._history(ip_obj, action, old_status, status, user, fields)
        SubnetService.recalculate_usage(ip_obj.subnet)
        return ip_obj

    @classmethod
    @transaction.atomic
    def allocate_ip(cls, ip_obj, data, user=None):
        if ip_obj.status not in cls.ALLOCATABLE_STATUSES:
            raise ValidationError({"status": "当前 IP 不是可分配状态。"})
        fields = {
            "hostname": data.get("hostname") or "",
            "device_name": data.get("device_name") or "",
            "owner": data.get("owner") or "",
            "mac_address": data.get("mac_address") or "",
            "bind_type": data.get("bind_type") or "manual",
            "description": data.get("description") or "",
        }
        return cls.set_status(ip_obj, "used", user, "allocate", **fields)

    @classmethod
    @transaction.atomic
    def release_ip(cls, ip_obj, user=None):
        if ip_obj.status == "gateway":
            raise ValidationError({"status": "网关地址不能释放。"})
        if ip_obj.status not in {"used", "reserved"}:
            raise ValidationError({"status": "只有已使用 IP 才能释放。"})
        return cls.set_status(ip_obj, "available", user, "release", **cls.CLEAR_FIELDS)

    @staticmethod
    def ping_ip(ip_address):
        return NetworkScanService.ping(ip_address)

    @staticmethod
    @transaction.atomic
    def record_ping_result(ip_obj, result):
        ip_obj.last_scan_status = result["status"]
        ip_obj.last_scan_time = timezone.now()
        ip_obj.save(update_fields=["last_scan_status", "last_scan_time", "updated_at"])
        return NetworkScanRecord.objects.create(
            ip_address=ip_obj.ip_address,
            subnet=ip_obj.subnet,
            status=result["status"],
            response_time=result.get("response_time", ""),
            error_message=result.get("error_message", ""),
        )

    @staticmethod
    def scan_subnet(subnet):
        return NetworkScanService.scan_subnet(subnet)


class IPAMService:
    ALLOCATABLE_STATUSES = IPAddressService.ALLOCATABLE_STATUSES
    CLEAR_FIELDS = IPAddressService.CLEAR_FIELDS

    @staticmethod
    def generate_ips(subnet):
        return SubnetService.generate_ips(subnet)

    @staticmethod
    def set_status(ip_obj, status, user=None, action="status_change", **fields):
        return IPAddressService.set_status(ip_obj, status, user=user, action=action, **fields)

    @staticmethod
    def allocate(ip_obj, user=None, **fields):
        return IPAddressService.allocate_ip(ip_obj, fields, user=user)

    @staticmethod
    def reserve(ip_obj, user=None, **fields):
        if ip_obj.status not in {"available", "used"}:
            raise ValidationError({"status": "当前 IP 不能设置为预留。"})
        return IPAddressService.set_status(ip_obj, "reserved", user=user, action="reserve", **fields)

    @staticmethod
    def release(ip_obj, user=None):
        if ip_obj.status in {"dhcp_dynamic", "dhcp_reserved"}:
            raise ValidationError({"status": "DHCP 联动地址不能从 IPAM 手动释放。"})
        return IPAddressService.release_ip(ip_obj, user=user)

    @staticmethod
    def utilization():
        rows = []
        for subnet in Subnet.objects.select_related("region", "vlan").all():
            SubnetService.recalculate_usage(subnet)
            rows.append(
                {
                    "subnet_id": subnet.id,
                    "cidr": subnet.cidr,
                    "address_space": subnet.region.name if subnet.region else "-",
                    "total": subnet.total_ips,
                    "available": subnet.ip_addresses.filter(status="available").count(),
                    "used": subnet.ip_addresses.filter(status="used").count(),
                    "reserved": subnet.ip_addresses.filter(status="reserved").count(),
                    "dhcp_dynamic": subnet.ip_addresses.filter(status="dhcp_dynamic").count(),
                    "dhcp_reserved": subnet.ip_addresses.filter(status="dhcp_reserved").count(),
                    "utilization": subnet.utilization_rate,
                    "alert": "red" if subnet.utilization_rate >= 90 else "yellow" if subnet.utilization_rate >= 80 else "normal",
                }
            )
        return rows

    @staticmethod
    def subnet_utilization(subnet):
        SubnetService.recalculate_usage(subnet)
        alert = "red" if subnet.utilization_rate >= 90 else "yellow" if subnet.utilization_rate >= 80 else "normal"
        return {
            "subnet_id": subnet.id,
            "cidr": subnet.cidr,
            "total": subnet.total_ips,
            "used": subnet.used_ips,
            "utilization": subnet.utilization_rate,
            "alert": alert,
        }
