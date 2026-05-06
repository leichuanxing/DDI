from django import forms
import ipaddress

from .models import IPAddress, Region, Subnet, VLAN
from .services import SubnetService
from .utils import normalize_mac, validate_mac


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ["name", "code", "description"]


class VLANForm(forms.ModelForm):
    class Meta:
        model = VLAN
        fields = ["vlan_id", "name", "region", "usage", "gateway", "description"]


class SubnetForm(forms.ModelForm):
    auto_generate_ips = forms.BooleanField(required=False, initial=True, label="自动生成 IP 地址")

    class Meta:
        model = Subnet
        fields = ["name", "cidr", "gateway", "region", "vlan", "usage", "status", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True
        self.fields["gateway"].required = True
        self.fields["region"].required = True
        region_id = None
        if self.is_bound:
            region_id = self.data.get("region") or None
        elif self.instance and self.instance.pk and self.instance.region_id:
            region_id = self.instance.region_id
        if region_id:
            self.fields["vlan"].queryset = VLAN.objects.filter(region_id=region_id).order_by("vlan_id", "name")
        else:
            self.fields["vlan"].queryset = VLAN.objects.select_related("region").order_by("region__name", "vlan_id", "name")

    def clean_cidr(self):
        cidr = self.cleaned_data["cidr"]
        return str(ipaddress.ip_network(cidr, strict=False))

    def clean(self):
        cleaned = super().clean()
        cidr = cleaned.get("cidr")
        gateway = cleaned.get("gateway")
        region = cleaned.get("region")
        vlan = cleaned.get("vlan")
        if cidr:
            overlap = SubnetService.check_subnet_overlap(cidr, exclude_id=self.instance.pk if self.instance else None)
            if overlap:
                self.add_error("cidr", f"子网与 {overlap.cidr} 重叠。")
        if gateway and cidr:
            network = ipaddress.ip_network(cidr, strict=False)
            if ipaddress.ip_address(gateway) not in network:
                self.add_error("gateway", "网关必须属于当前子网。")
        if vlan and region and vlan.region_id != region.id:
            self.add_error("vlan", "所选 VLAN 必须属于当前区域。")
        return cleaned


class IPAddressEditForm(forms.ModelForm):
    class Meta:
        model = IPAddress
        fields = [
            "status",
            "hostname",
            "device_name",
            "owner",
            "mac_address",
            "bind_type",
            "description",
        ]


class IPAllocateForm(forms.Form):
    hostname = forms.CharField(max_length=100, required=False, label="主机名")
    device_name = forms.CharField(max_length=100, required=False, label="设备名")
    owner = forms.CharField(max_length=100, required=False, label="使用人")
    mac_address = forms.CharField(max_length=50, required=False, label="MAC 地址")
    bind_type = forms.ChoiceField(
        choices=IPAddress.BIND_TYPE_CHOICES,
        required=False,
        label="绑定方式",
        initial="manual",
    )
    description = forms.CharField(required=False, widget=forms.Textarea, label="备注")

    def clean_mac_address(self):
        value = normalize_mac(self.cleaned_data.get("mac_address"))
        if not value:
            return ""
        if not validate_mac(value):
            raise forms.ValidationError("MAC 地址格式不正确。")
        return value


class NetworkScanForm(forms.Form):
    ip_address = forms.GenericIPAddressField(protocol="IPv4", label="IP 地址")


class SubnetScanForm(forms.Form):
    subnet = forms.ModelChoiceField(queryset=Subnet.objects.none(), label="子网")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subnet"].queryset = Subnet.objects.order_by("cidr")


class NetworkProbePingForm(forms.Form):
    MODE_CHOICES = (
        ("single", "单 IP Ping"),
        ("subnet", "子网批量 Ping"),
    )
    mode = forms.ChoiceField(label="模式", choices=MODE_CHOICES, initial="single")
    ip = forms.GenericIPAddressField(label="IP 地址", required=False, protocol="IPv4")
    subnet = forms.ModelChoiceField(
        queryset=Subnet.objects.none(),
        label="子网",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subnet"].queryset = Subnet.objects.order_by("cidr")

    def clean(self):
        data = super().clean()
        mode = data.get("mode")
        if mode == "single":
            if not data.get("ip"):
                self.add_error("ip", "请填写要探测的 IP。")
        elif mode == "subnet":
            if not data.get("subnet"):
                self.add_error("subnet", "请选择子网。")
        return data


class NetworkProbePortForm(forms.Form):
    host = forms.GenericIPAddressField(label="目标 IP", protocol="IPv4")
    ports = forms.CharField(
        label="端口",
        initial="22,80,443,445,3389",
        help_text="逗号分隔，或范围如 8000-8010，单次最多 128 个端口。",
    )


class NetworkProbeArpForm(forms.Form):
    switch_ip = forms.GenericIPAddressField(label="交换机管理 IP", protocol="IPv4")
    ssh_port = forms.IntegerField(label="SSH 端口", min_value=1, max_value=65535, initial=22)
    ssh_username = forms.CharField(label="SSH 用户名", max_length=128)
    ssh_password = forms.CharField(
        label="SSH 密码",
        max_length=256,
        widget=forms.PasswordInput(),
    )
    ssh_commands = forms.CharField(
        label="远程执行的命令",
        widget=forms.Textarea(attrs={"rows": 8, "cols": 80}),
        initial="terminal length 0\nshow ip arp",
        help_text=(
            "每行一条命令，按顺序在设备上执行（SSH exec）。"
            "可按厂商替换，例如 H3C「display arp」、Linux「arp -a」或「ip neigh」等。"
        ),
    )

    def clean_ssh_commands(self):
        text = (self.cleaned_data.get("ssh_commands") or "").strip()
        if not text:
            raise forms.ValidationError("请至少填写一条要在交换机上执行的命令。")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise forms.ValidationError("请至少填写一条要在交换机上执行的命令。")
        return "\n".join(lines)
