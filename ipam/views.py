import ipaddress

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from tasks.models import SystemTask
from tasks.services import TaskService

from .forms import (
    IPAddressEditForm,
    IPAllocateForm,
    NetworkProbeArpForm,
    NetworkProbePingForm,
    NetworkProbePortForm,
    NetworkScanForm,
    RegionForm,
    SubnetForm,
    SubnetScanForm,
    VLANForm,
)
from .models import IPAddress, NetworkScanRecord, Region, Subnet, VLAN
from .probe import (
    MAX_SUBNET_PING_HOSTS,
    NETWORK_PROBE_TASK_LABELS,
    NETWORK_PROBE_TASK_TYPES,
    NETWORK_PROBE_TASK_TYPE_SET,
)
from .services import IPAddressService, NetworkScanService, SubnetService

# 子网详情 — IP 清单分页
SUBNET_DETAIL_PAGE_SIZES = (25, 50, 100, 200, 500)
SUBNET_DETAIL_DEFAULT_PAGE_SIZE = 50


def _subnet_containing_ip(ip_text: str) -> Subnet | None:
    """在 IPAM 中查找包含该 IPv4 的子网（无重叠假设下至多一个）。"""
    ip_text = (ip_text or "").strip()
    if not ip_text:
        return None
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return None
    for s in Subnet.objects.only("id", "cidr"):
        try:
            if addr in s.network:
                return s
        except ValueError:
            continue
    return None


def _subnet_for_probe_ping_allocate(result_data: dict) -> Subnet | None:
    """子网批量 Ping 用任务里的 subnet_id；单 IP Ping 则在 IPAM 子网中查找包含该地址的网段。"""
    mode = (result_data.get("mode") or "").strip()
    if mode == "subnet":
        sid = result_data.get("subnet_id")
        if not sid:
            return None
        return Subnet.objects.filter(pk=sid).first()
    if mode == "single":
        results = result_data.get("results") or []
        if not results:
            return None
        return _subnet_containing_ip((results[0].get("ip") or "").strip())
    return None


def _subnet_detail_page_size(request):
    raw = request.GET.get("per_page")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return SUBNET_DETAIL_DEFAULT_PAGE_SIZE
    if n in SUBNET_DETAIL_PAGE_SIZES:
        return n
    return SUBNET_DETAIL_DEFAULT_PAGE_SIZE


def _base_context(request, page_title, page_description, active_menu):
    return {
        "section_title": "IP 地址管理",
        "page_title": page_title,
        "page_description": page_description,
        "active_section": "ipam",
        "active_menu": active_menu,
        "is_admin": bool(request.user.is_staff or request.user.is_superuser),
    }


def _json(success, message, status=200, **data):
    payload = {"success": success, "message": message}
    if data:
        payload["data"] = data
    return JsonResponse(payload, status=status)


def admin_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "当前账号只有查看权限。")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapped


@login_required
def region_list(request):
    regions = Region.objects.annotate(
        subnet_count=Count("subnets", distinct=True),
        vlan_count=Count("vlans", distinct=True),
    ).order_by("id")
    context = {
        **_base_context(request, "区域管理", "统一维护区域信息和关联网络资源。", "regions"),
        "regions": regions,
        "create_url": reverse("ipam-region-add"),
        "primary_action": "+ 新增区域",
    }
    return render(request, "ipam/region_list.html", context)


@admin_required
def region_add(request):
    form = RegionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "区域新增成功。")
        return redirect("ipam-region-list")
    context = {
        **_base_context(request, "新增区域", "创建新的区域编码和描述。", "regions"),
        "form": form,
        "submit_text": "保存区域",
        "back_url": reverse("ipam-region-list"),
    }
    return render(request, "ipam/region_form.html", context)


@admin_required
def region_edit(request, pk):
    region = get_object_or_404(Region, pk=pk)
    form = RegionForm(request.POST or None, instance=region)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "区域更新成功。")
        return redirect("ipam-region-list")
    context = {
        **_base_context(request, "编辑区域", "更新区域基础信息。", "regions"),
        "form": form,
        "submit_text": "保存修改",
        "back_url": reverse("ipam-region-list"),
        "object": region,
    }
    return render(request, "ipam/region_form.html", context)


@admin_required
def region_delete(request, pk):
    region = get_object_or_404(Region, pk=pk)
    vlan_count = region.vlans.count()
    subnet_count = region.subnets.count()
    if vlan_count or subnet_count:
        return _json(False, f"该区域下还有 {vlan_count} 个 VLAN、{subnet_count} 个子网，无法删除。", status=400)
    region.delete()
    return _json(True, "区域已删除。")


@login_required
def vlan_list(request):
    vlans = (
        VLAN.objects.select_related("region")
        .annotate(subnet_count=Count("subnets", distinct=True))
        .order_by("region__name", "vlan_id")
    )
    context = {
        **_base_context(request, "VLAN 管理", "按区域维护 VLAN、用途和默认网关。", "vlans"),
        "vlans": vlans,
        "create_url": reverse("ipam-vlan-add"),
        "primary_action": "+ 新增VLAN",
    }
    return render(request, "ipam/vlan_list.html", context)


@admin_required
def vlan_add(request):
    form = VLANForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "VLAN 新增成功。")
        return redirect("ipam-vlan-list")
    context = {
        **_base_context(request, "新增 VLAN", "创建 VLAN 与区域关联信息。", "vlans"),
        "form": form,
        "submit_text": "保存 VLAN",
        "back_url": reverse("ipam-vlan-list"),
    }
    return render(request, "ipam/vlan_form.html", context)


@admin_required
def vlan_edit(request, pk):
    vlan = get_object_or_404(VLAN, pk=pk)
    form = VLANForm(request.POST or None, instance=vlan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "VLAN 更新成功。")
        return redirect("ipam-vlan-list")
    context = {
        **_base_context(request, "编辑 VLAN", "更新 VLAN 基础信息。", "vlans"),
        "form": form,
        "submit_text": "保存修改",
        "back_url": reverse("ipam-vlan-list"),
        "object": vlan,
    }
    return render(request, "ipam/vlan_form.html", context)


@admin_required
def vlan_delete(request, pk):
    vlan = get_object_or_404(VLAN, pk=pk)
    subnet_count = vlan.subnets.count()
    if subnet_count:
        return _json(False, f"该 VLAN 下还有 {subnet_count} 个子网，无法删除。", status=400)
    vlan.delete()
    return _json(True, "VLAN 已删除。")


@login_required
def subnet_list(request):
    keyword = (request.GET.get("keyword") or "").strip()
    region_id = (request.GET.get("region") or "").strip()
    subnets = Subnet.objects.select_related("region", "vlan").all()
    if keyword:
        subnets = subnets.filter(Q(name__icontains=keyword) | Q(cidr__icontains=keyword))
    if region_id:
        subnets = subnets.filter(region_id=region_id)
    subnet_rows = []
    for subnet in subnets.order_by("cidr"):
        SubnetService.recalculate_usage(subnet)
        subnet_rows.append(subnet)
    context = {
        **_base_context(request, "子网管理", "按区域查看和维护子网、网关和 IP 使用情况。", "subnets"),
        "subnets": subnet_rows,
        "regions": Region.objects.order_by("name"),
        "keyword": keyword,
        "region_id": region_id,
        "create_url": reverse("ipam-subnet-add"),
        "primary_action": "+ 新增子网",
    }
    return render(request, "ipam/subnet_list.html", context)


@admin_required
def subnet_add(request):
    form = SubnetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        subnet = form.save()
        if form.cleaned_data.get("auto_generate_ips"):
            SubnetService.generate_ips(subnet)
        else:
            SubnetService.recalculate_usage(subnet)
        messages.success(request, "子网新增成功。")
        return redirect("ipam-subnet-list")
    context = {
        **_base_context(request, "新增子网", "录入 CIDR、网关、区域与 VLAN。", "subnets"),
        "form": form,
        "submit_text": "保存子网",
        "back_url": reverse("ipam-subnet-list"),
    }
    return render(request, "ipam/subnet_form.html", context)


@login_required
def subnet_detail(request, pk):
    subnet = get_object_or_404(Subnet.objects.select_related("region", "vlan"), pk=pk)
    SubnetService.recalculate_usage(subnet)
    subnet.refresh_from_db(fields=["used_ips", "total_ips", "updated_at"])
    status_counts = SubnetService.ip_status_breakdown(subnet)
    available_count = status_counts.get("available", 0)

    status_filter = (request.GET.get("status") or "").strip()
    valid_statuses = {code for code, _ in IPAddress.STATUS_CHOICES}
    if status_filter and status_filter not in valid_statuses:
        status_filter = ""

    per_page = _subnet_detail_page_size(request)

    host_ips = None
    if not status_filter:
        host_ips = SubnetService.host_addresses_enumerated_flat(subnet)

    ip_list_merged = host_ips is not None
    ip_list_truncated = not status_filter and host_ips is None
    untracked_host_count = 0

    if ip_list_merged:
        page_obj = SubnetService.paginate_merged_subnet_ip_page(
            subnet, host_ips, request.GET.get("page"), per_page
        )
        db_cnt = subnet.ip_addresses.count()
        untracked_host_count = max(0, len(host_ips) - db_cnt)
        free_address_slots = untracked_host_count + available_count
    else:
        ip_queryset = subnet.ip_addresses.order_by("ip_address")
        if status_filter:
            ip_queryset = ip_queryset.filter(status=status_filter)
        paginator = Paginator(ip_queryset, per_page)
        page_obj = paginator.get_page(request.GET.get("page"))
        free_address_slots = available_count

    if ip_list_merged:
        ip_list_empty = len(host_ips) == 0
    else:
        ip_list_empty = page_obj.paginator.count == 0

    status_breakdown = [
        {"code": code, "label": label, "count": status_counts.get(code, 0)}
        for code, label in IPAddress.STATUS_CHOICES
    ]
    context = {
        **_base_context(
            request,
            "子网详情",
            "查看网段基础信息、IP 利用率与地址清单。",
            "subnets",
        ),
        "subnet": subnet,
        "page_obj": page_obj,
        "status_filter": status_filter,
        "status_choices": IPAddress.STATUS_CHOICES,
        "status_breakdown": status_breakdown,
        "available_count": available_count,
        "free_address_slots": free_address_slots,
        "per_page": per_page,
        "per_page_choices": SUBNET_DETAIL_PAGE_SIZES,
        "ip_list_merged": ip_list_merged,
        "ip_list_empty": ip_list_empty,
        "ip_list_truncated": ip_list_truncated,
        "untracked_host_count": untracked_host_count,
        "merge_host_cap": SubnetService.MAX_MERGED_SUBNET_HOSTS,
    }
    return render(request, "ipam/subnet_detail.html", context)


@admin_required
def subnet_edit(request, pk):
    subnet = get_object_or_404(Subnet, pk=pk)
    form = SubnetForm(request.POST or None, instance=subnet)
    if request.method == "POST" and form.is_valid():
        subnet = form.save()
        SubnetService.recalculate_usage(subnet)
        messages.success(request, "子网更新成功。")
        return redirect("ipam-subnet-list")
    context = {
        **_base_context(request, "编辑子网", "修改子网信息后会重新校验 CIDR 和 VLAN。", "subnets"),
        "form": form,
        "submit_text": "保存修改",
        "back_url": reverse("ipam-subnet-list"),
        "object": subnet,
    }
    return render(request, "ipam/subnet_form.html", context)


@admin_required
def subnet_delete(request, pk):
    subnet = get_object_or_404(Subnet, pk=pk)
    ip_count = subnet.ip_addresses.count()
    subnet.delete()
    return _json(True, f"子网已删除，同时删除 {ip_count} 个关联 IP。")


@admin_required
def subnet_generate_ips(request, pk):
    subnet = get_object_or_404(Subnet, pk=pk)
    result = SubnetService.generate_ips(subnet)
    return _json(True, "IP 地址生成完成。", **result)


@admin_required
def subnet_ip_allocate(request, subnet_pk):
    """子网详情：按 IP 字符串分配（支持尚未写入库的「空闲」主机位）。"""
    subnet = get_object_or_404(Subnet, pk=subnet_pk)
    ip_text = (request.POST.get("ip_address") or "").strip()
    if not ip_text:
        return _json(False, "缺少 IP 地址。", status=400)
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return _json(False, "IP 地址格式不正确。", status=400)
    if addr not in subnet.network:
        return _json(False, "该 IP 不属于当前子网。", status=400)

    gateway_str = str(subnet.gateway) if subnet.gateway else ""
    if gateway_str and ip_text == gateway_str:
        return _json(False, "网关地址不能直接分配。", status=400)

    form = IPAllocateForm(request.POST)
    if not form.is_valid():
        return _json(False, "分配参数校验失败。", status=400, errors=form.errors)

    ip_obj, _created = IPAddress.objects.get_or_create(
        subnet=subnet,
        ip_address=ip_text,
        defaults={"status": "available"},
    )
    if ip_obj.status == "gateway":
        return _json(False, "网关地址不能直接分配。", status=400)
    try:
        IPAddressService.allocate_ip(ip_obj, form.cleaned_data, user=request.user)
    except ValidationError as exc:
        return _json(False, exc.message_dict.get("status", [str(exc)])[0], status=400)
    return _json(True, "IP 分配成功。")


@login_required
def ip_list(request):
    keyword = (request.GET.get("keyword") or "").strip()
    status_value = (request.GET.get("status") or "").strip()
    subnet_id = (request.GET.get("subnet") or "").strip()

    queryset = IPAddress.objects.select_related("subnet").all()
    if keyword:
        queryset = queryset.filter(
            Q(ip_address__icontains=keyword)
            | Q(hostname__icontains=keyword)
            | Q(mac_address__icontains=keyword)
            | Q(device_name__icontains=keyword)
        )
    if status_value:
        queryset = queryset.filter(status=status_value)
    if subnet_id:
        queryset = queryset.filter(subnet_id=subnet_id)

    paginator = Paginator(queryset.order_by("ip_address"), 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        **_base_context(request, "IP 地址", "查看与筛选 IP，分配、编辑或释放。", "ips"),
        "page_obj": page_obj,
        "status_value": status_value,
        "subnet_id": subnet_id,
        "keyword": keyword,
        "subnets": Subnet.objects.order_by("cidr"),
        "status_choices": IPAddress.STATUS_CHOICES,
    }
    return render(request, "ipam/ip_list.html", context)


@admin_required
def ip_allocate(request, pk):
    ip_obj = get_object_or_404(IPAddress.objects.select_related("subnet"), pk=pk)
    form = IPAllocateForm(request.POST)
    if not form.is_valid():
        return _json(False, "分配参数校验失败。", status=400, errors=form.errors)
    try:
        IPAddressService.allocate_ip(ip_obj, form.cleaned_data, user=request.user)
    except ValidationError as exc:
        return _json(False, exc.message_dict.get("status", [str(exc)])[0], status=400)
    return _json(True, "IP 分配成功。")


@admin_required
def ip_release(request, pk):
    ip_obj = get_object_or_404(IPAddress, pk=pk)
    try:
        IPAddressService.release_ip(ip_obj, user=request.user)
    except ValidationError as exc:
        return _json(False, exc.message_dict.get("status", [str(exc)])[0], status=400)
    return _json(True, "IP 已释放。")


@admin_required
def ip_edit(request, pk):
    ip_obj = get_object_or_404(IPAddress.objects.select_related("subnet"), pk=pk)
    form = IPAddressEditForm(request.POST or None, instance=ip_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "IP 信息已更新。")
        return redirect("ipam-ip-list")
    context = {
        **_base_context(request, "编辑 IP", "更新主机名、设备名和绑定方式。", "ips"),
        "form": form,
        "ip_obj": ip_obj,
        "submit_text": "保存修改",
        "back_url": reverse("ipam-ip-list"),
    }
    return render(request, "ipam/ip_form.html", context)


@admin_required
def ip_delete(request, pk):
    ip_obj = get_object_or_404(IPAddress, pk=pk)
    if ip_obj.status == "gateway":
        return _json(False, "网关地址不能删除。", status=400)
    subnet = ip_obj.subnet
    ip_obj.delete()
    SubnetService.recalculate_usage(subnet)
    return _json(True, "IP 已删除。")


@login_required
def ip_ping(request, pk):
    ip_obj = get_object_or_404(IPAddress.objects.select_related("subnet"), pk=pk)
    result = IPAddressService.ping_ip(ip_obj.ip_address)
    IPAddressService.record_ping_result(ip_obj, result)
    return _json(True, "探测完成。", **result)


@login_required
def network_scan(request):
    task_type_keys = [k for k, _ in NETWORK_PROBE_TASK_TYPES]
    probe_tasks = (
        SystemTask.objects.filter(task_type__in=task_type_keys)
        .select_related("created_by")
        .order_by("-created_at")[:300]
    )
    context = {
        **_base_context(
            request,
            "网络探测",
            "通过异步任务执行 Ping 扫描、端口扫描或交换机 ARP（SSH）获取。",
            "network-scan",
        ),
        "probe_tasks": probe_tasks,
    }
    return render(request, "ipam/network_scan.html", context)


@login_required
def network_probe_ping_new(request):
    if request.method == "POST":
        form = NetworkProbePingForm(request.POST)
        if form.is_valid():
            mode = form.cleaned_data["mode"]
            if mode == "single":
                payload = {"mode": "single", "ip": str(form.cleaned_data["ip"])}
            else:
                payload = {"mode": "subnet", "subnet_id": form.cleaned_data["subnet"].pk}
            TaskService.enqueue("network_ping_scan", "ipam", payload, request.user)
            messages.success(request, "Ping 扫描任务已提交，请稍后在列表中查看状态。")
            return redirect("ipam-network-scan")
    else:
        form = NetworkProbePingForm()
    context = {
        **_base_context(request, "新建 Ping 扫描", "单 IP 或整段子网批量 Ping。", "network-scan"),
        "form": form,
        "submit_text": "提交任务",
        "back_url": reverse("ipam-network-scan"),
        "max_subnet_hosts": MAX_SUBNET_PING_HOSTS,
    }
    return render(request, "ipam/network_probe_ping.html", context)


@login_required
def network_probe_port_new(request):
    if request.method == "POST":
        form = NetworkProbePortForm(request.POST)
        if form.is_valid():
            payload = {
                "host": str(form.cleaned_data["host"]),
                "ports": form.cleaned_data["ports"].strip(),
            }
            TaskService.enqueue("network_port_scan", "ipam", payload, request.user)
            messages.success(request, "端口扫描任务已提交，请稍后在列表中查看状态。")
            return redirect("ipam-network-scan")
    else:
        form = NetworkProbePortForm()
    context = {
        **_base_context(request, "新建端口扫描", "TCP 连接探测指定端口是否开放。", "network-scan"),
        "form": form,
        "submit_text": "提交任务",
        "back_url": reverse("ipam-network-scan"),
    }
    return render(request, "ipam/network_probe_port.html", context)


@login_required
def network_probe_arp_new(request):
    if request.method == "POST":
        form = NetworkProbeArpForm(request.POST)
        if form.is_valid():
            payload = {
                "switch_ip": str(form.cleaned_data["switch_ip"]),
                "ssh_port": form.cleaned_data["ssh_port"],
                "ssh_username": form.cleaned_data["ssh_username"].strip(),
                "ssh_password": form.cleaned_data["ssh_password"],
                "ssh_commands": form.cleaned_data["ssh_commands"],
            }
            TaskService.enqueue("network_switch_arp", "ipam", payload, request.user)
            messages.success(request, "交换机 ARP 获取任务已提交，请稍后在列表中查看状态。")
            return redirect("ipam-network-scan")
    else:
        form = NetworkProbeArpForm()
    context = {
        **_base_context(
            request,
            "新建交换机 ARP 获取",
            "通过 SSH 登录交换机并执行你填写的命令，从输出中解析 IPv4 与 MAC（常见如 Cisco「show ip arp」）。",
            "network-scan",
        ),
        "form": form,
        "submit_text": "提交任务",
        "back_url": reverse("ipam-network-scan"),
    }
    return render(request, "ipam/network_probe_arp.html", context)


@login_required
def network_probe_task_detail(request, pk):
    task = get_object_or_404(SystemTask.objects.select_related("created_by"), pk=pk)
    if task.task_type not in NETWORK_PROBE_TASK_TYPE_SET:
        raise Http404()
    probe_logs = task.logs.order_by("created_at")[:500]
    resp = task.response_payload or {}
    probe_result_data = dict(resp.get("data") or {})
    probe_ping_allocate_subnet = None
    if task.task_type == "network_ping_scan":
        rows = probe_result_data.get("results")
        if rows:
            def _ping_row_ip_key(row: dict) -> int:
                try:
                    return int(ipaddress.ip_address(row.get("ip") or "0.0.0.0"))
                except ValueError:
                    return 0

            probe_result_data["results"] = sorted(rows, key=_ping_row_ip_key)
        probe_ping_allocate_subnet = _subnet_for_probe_ping_allocate(probe_result_data)
    probe_arp_rows: list[dict] = []
    if task.task_type == "network_switch_arp":
        for e in probe_result_data.get("entries") or []:
            ip_txt = (e.get("ip") or "").strip()
            probe_arp_rows.append(
                {
                    "ip": ip_txt,
                    "mac": (e.get("mac") or "").strip(),
                    "subnet": _subnet_containing_ip(ip_txt),
                }
            )
    probe_arp_some_without_subnet = any(
        row.get("subnet") is None for row in probe_arp_rows
    )
    probe_failure_message = ""
    if not resp.get("success"):
        probe_failure_message = (resp.get("message") or "").strip()
    is_admin = bool(request.user.is_staff or request.user.is_superuser)
    show_probe_allocate_modal = is_admin and (
        (task.task_type == "network_ping_scan" and bool(probe_result_data.get("results")))
        or (task.task_type == "network_switch_arp" and bool(probe_arp_rows))
    )
    context = {
        **_base_context(
            request,
            f"探测任务 #{task.id}",
            NETWORK_PROBE_TASK_LABELS.get(task.task_type, task.task_type),
            "network-scan",
        ),
        "probe_task": task,
        "probe_logs": probe_logs,
        "back_url": reverse("ipam-network-scan"),
        "probe_result_data": probe_result_data,
        "probe_ping_allocate_subnet": probe_ping_allocate_subnet,
        "probe_arp_rows": probe_arp_rows,
        "probe_arp_some_without_subnet": probe_arp_some_without_subnet,
        "probe_failure_message": probe_failure_message,
        "show_probe_allocate_modal": show_probe_allocate_modal,
    }
    return render(request, "ipam/network_probe_task_detail.html", context)


@login_required
def network_probe_task_delete(request, pk):
    if request.method != "POST":
        return _json(False, "请使用 POST 删除任务。", status=405)
    if not (request.user.is_staff or request.user.is_superuser):
        return _json(False, "当前账号无权限删除任务。", status=403)
    task = get_object_or_404(SystemTask, pk=pk)
    if task.task_type not in NETWORK_PROBE_TASK_TYPE_SET:
        return _json(False, "该任务不是网络探测任务，不能从此入口删除。", status=400)
    task.delete()
    return _json(True, "探测任务已删除。")


@login_required
def network_scan_ping(request):
    form = NetworkScanForm(request.POST)
    if not form.is_valid():
        return _json(False, "请输入合法的 IPv4 地址。", status=400, errors=form.errors)
    ip_value = form.cleaned_data["ip_address"]
    result = NetworkScanService.ping(ip_value)
    ip_obj = IPAddress.objects.filter(ip_address=ip_value).first()
    if ip_obj:
        record = IPAddressService.record_ping_result(ip_obj, result)
    else:
        record = NetworkScanRecord.objects.create(
            ip_address=ip_value,
            status=result["status"],
            response_time=result.get("response_time", ""),
            error_message=result.get("error_message", ""),
        )
    return _json(True, "单 IP 探测完成。", record_id=record.id, **result)


@login_required
def network_scan_subnet(request):
    form = SubnetScanForm(request.POST)
    if not form.is_valid():
        return _json(False, "请选择要探测的子网。", status=400, errors=form.errors)
    subnet = form.cleaned_data["subnet"]
    if subnet.ip_addresses.count() > 254:
        return _json(False, "批量探测一次最多 254 个 IP。", status=400)
    records = NetworkScanService.scan_subnet(subnet)
    return _json(True, "子网批量探测完成。", count=len(records))
