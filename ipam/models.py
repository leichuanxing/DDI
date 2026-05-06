import ipaddress
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


class AddressSpace(models.Model):
    name = models.CharField("地址空间名称", max_length=64, unique=True)
    code = models.CharField("地址空间编码", max_length=64, unique=True)
    description = models.TextField("描述", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "地址空间"
        verbose_name_plural = "地址空间"

    def __str__(self):
        return self.name


class Region(models.Model):
    name = models.CharField(max_length=100, verbose_name="区域名称")
    code = models.CharField(max_length=50, unique=True, verbose_name="区域编码")
    description = models.TextField(blank=True, null=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "区域"
        verbose_name_plural = "区域"
        ordering = ["name", "code"]

    def __str__(self):
        return self.name


class VLAN(models.Model):
    vlan_id = models.IntegerField(verbose_name="VLAN ID")
    name = models.CharField(max_length=100, verbose_name="VLAN名称")
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="vlans",
        verbose_name="所属区域",
    )
    usage = models.CharField(max_length=100, blank=True, null=True, verbose_name="用途")
    gateway = models.GenericIPAddressField(blank=True, null=True, verbose_name="网关")
    description = models.TextField(blank=True, null=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "VLAN"
        verbose_name_plural = "VLAN"
        unique_together = ("region", "vlan_id")
        ordering = ["region__name", "vlan_id", "name"]

    def clean(self):
        if self.vlan_id is None or not 1 <= int(self.vlan_id) <= 4094:
            raise ValidationError({"vlan_id": "VLAN ID 必须在 1 到 4094 之间。"})

    def __str__(self):
        return f"VLAN {self.vlan_id} · {self.name}"


class Subnet(models.Model):
    STATUS_CHOICES = [
        ("enabled", "启用"),
        ("disabled", "停用"),
        ("planned", "规划中"),
    ]

    address_space = models.ForeignKey(
        AddressSpace,
        verbose_name="地址空间",
        related_name="subnets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    name = models.CharField("子网名称", max_length=100, blank=True)
    cidr = models.CharField("CIDR", max_length=64, unique=True)
    gateway = models.GenericIPAddressField("网关", null=True, blank=True)
    netmask = models.CharField("掩码", max_length=64, blank=True)
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="subnets",
        verbose_name="所属区域",
        null=True,
        blank=True,
    )
    vlan = models.ForeignKey(
        VLAN,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subnets",
        verbose_name="VLAN",
    )
    location = models.CharField("位置", max_length=128, blank=True)
    usage = models.CharField("用途", max_length=100, blank=True, null=True)
    usage_type = models.CharField("用途(兼容)", max_length=64, blank=True)
    total_ips = models.IntegerField("IP总数", default=0)
    used_ips = models.IntegerField("已使用IP数", default=0)
    description = models.TextField("描述", blank=True)
    status = models.CharField("状态", max_length=16, choices=STATUS_CHOICES, default="enabled")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "子网"
        verbose_name_plural = "子网"
        ordering = ["cidr"]

    def clean(self):
        try:
            net = ipaddress.ip_network(self.cidr, strict=False)
        except ValueError as exc:
            raise ValidationError({"cidr": f"CIDR 格式错误: {exc}"})
        self.cidr = str(net)
        self.netmask = str(net.netmask)
        self.total_ips = max(net.num_addresses - 2, 0)

        if self.gateway:
            try:
                gateway = ipaddress.ip_address(self.gateway)
            except ValueError as exc:
                raise ValidationError({"gateway": f"网关格式错误: {exc}"})
            if gateway not in net:
                raise ValidationError({"gateway": "网关必须属于当前子网。"})

        if self.vlan and self.region and self.vlan.region_id != self.region_id:
            raise ValidationError({"vlan": "所选 VLAN 必须属于当前区域。"})

        overlap_qs = Subnet.objects.exclude(pk=self.pk).exclude(cidr="")
        for other in overlap_qs.only("id", "cidr"):
            try:
                if net.overlaps(ipaddress.ip_network(other.cidr, strict=False)):
                    raise ValidationError({"cidr": f"子网与 {other.cidr} 重叠。"})
            except ValueError:
                continue

        if self.vlan:
            if not self.gateway and self.vlan.gateway:
                self.gateway = self.vlan.gateway
        if self.usage and not self.usage_type:
            self.usage_type = self.usage
        if self.usage_type and not self.usage:
            self.usage = self.usage_type
        if not self.name:
            self.name = self.cidr

    @property
    def network(self):
        return ipaddress.ip_network(self.cidr, strict=False)

    @property
    def network_address(self):
        return str(self.network.network_address)

    @property
    def broadcast_address(self):
        if self.network.version == 4:
            return str(self.network.broadcast_address)
        return ""

    @property
    def utilization_rate(self):
        if not self.total_ips:
            return 0.0
        return round((self.used_ips / self.total_ips) * 100, 1)

    def __str__(self):
        return f"{self.name} ({self.cidr})"


class IPAddress(models.Model):
    STATUS_CHOICES = [
        ("available", "空闲"),
        ("used", "已使用"),
        ("gateway", "网关"),
        ("disabled", "禁用"),
        ("reserved", "预留"),
        ("dhcp_dynamic", "DHCP 动态分配"),
        ("dhcp_reserved", "DHCP 固定分配"),
    ]
    BIND_TYPE_CHOICES = [
        ("static", "静态绑定"),
        ("dhcp", "DHCP"),
        ("manual", "手动录入"),
    ]
    SCAN_STATUS_CHOICES = [
        ("online", "在线"),
        ("offline", "离线"),
        ("unknown", "未知"),
    ]

    subnet = models.ForeignKey(
        Subnet,
        verbose_name="所属子网",
        related_name="ip_addresses",
        on_delete=models.CASCADE,
    )
    ip_address = models.GenericIPAddressField("IP地址")
    status = models.CharField("状态", max_length=32, choices=STATUS_CHOICES, default="available")
    hostname = models.CharField("主机名", max_length=100, blank=True, null=True)
    device_name = models.CharField("设备名", max_length=100, blank=True, null=True)
    owner = models.CharField("使用人", max_length=100, blank=True, null=True)
    mac_address = models.CharField("MAC地址", max_length=50, blank=True, null=True)
    bind_type = models.CharField(
        "绑定方式",
        max_length=20,
        choices=BIND_TYPE_CHOICES,
        blank=True,
        null=True,
    )
    last_scan_status = models.CharField(
        "最近探测状态",
        max_length=20,
        choices=SCAN_STATUS_CHOICES,
        blank=True,
        null=True,
    )
    last_scan_time = models.DateTimeField("最近探测时间", blank=True, null=True)
    usage_type = models.CharField("用途", max_length=64, blank=True)
    department = models.CharField("部门", max_length=64, blank=True)
    description = models.TextField("备注", blank=True)
    dns_record = models.ForeignKey(
        "dns.DNSRecord",
        verbose_name="DNS记录",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    dhcp_reservation = models.ForeignKey(
        "dhcp.DHCPReservation",
        verbose_name="DHCP保留地址",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "IP 地址"
        verbose_name_plural = "IP 地址"
        unique_together = ("subnet", "ip_address")
        indexes = [
            models.Index(fields=["ip_address"]),
            models.Index(fields=["status"]),
            models.Index(fields=["last_scan_status"]),
        ]
        ordering = ["subnet__cidr", "ip_address"]

    def clean(self):
        try:
            ip_obj = ipaddress.ip_address(self.ip_address)
        except ValueError as exc:
            raise ValidationError({"ip_address": f"IP 地址格式错误: {exc}"})
        if self.subnet_id and ip_obj not in self.subnet.network:
            raise ValidationError({"ip_address": "IP 地址必须属于所属子网。"})
        if self.mac_address:
            mac = self.mac_address.replace("-", ":").lower()
            if not MAC_RE.match(mac):
                raise ValidationError({"mac_address": "MAC 地址格式不正确。"})
            self.mac_address = mac
        if self.status == "gateway" and self.bind_type in ("", None):
            self.bind_type = "manual"

    def __str__(self):
        return str(self.ip_address)


class IPAddressHistory(models.Model):
    ip_address = models.ForeignKey(
        IPAddress,
        verbose_name="IP 地址",
        related_name="histories",
        on_delete=models.CASCADE,
    )
    action = models.CharField("动作", max_length=64)
    old_status = models.CharField("原状态", max_length=32, blank=True)
    new_status = models.CharField("新状态", max_length=32, blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="操作人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    detail = models.JSONField("详情", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "IP 使用历史"
        verbose_name_plural = "IP 使用历史"
        ordering = ["-created_at"]


class NetworkScanRecord(models.Model):
    STATUS_CHOICES = [
        ("online", "在线"),
        ("offline", "离线"),
        ("unknown", "未知"),
    ]

    ip_address = models.GenericIPAddressField("IP地址")
    subnet = models.ForeignKey(
        Subnet,
        verbose_name="所属子网",
        related_name="scan_records",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    status = models.CharField("探测状态", max_length=20, choices=STATUS_CHOICES, default="unknown")
    response_time = models.CharField("响应时间", max_length=32, blank=True)
    error_message = models.CharField("错误信息", max_length=255, blank=True)
    scanned_at = models.DateTimeField("探测时间", auto_now_add=True)

    class Meta:
        verbose_name = "网络探测记录"
        verbose_name_plural = "网络探测记录"
        ordering = ["-scanned_at", "ip_address"]
