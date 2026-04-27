"""
IPAM 探测功能视图
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q, Count
from django.utils import timezone
from django.contrib import messages
import json
import threading

from ipam.models import Subnet, IPAddress
from ipam.scan_models import ScanTask, ScanResult, DiscoveryRule, ProbeHistory, SwitchDevice
from ipam.scanner import NetworkScanner, PortScanner, SwitchARPScanner
from common.logger import log_operation


# 全局扫描任务存储（用于跟踪正在运行的任务）
_running_tasks = {}


@login_required
def scan_index(request):
    """扫描功能首页 - 任务列表"""
    tasks = ScanTask.objects.all().order_by('-created_at')[:20]
    
    context = {
        'tasks': tasks,
        'page_title': '网络探测',
    }
    return render(request, 'ipam/scan/index.html', context)


@login_required
def create_scan_task(request):
    """创建扫描任务"""
    from .scan_forms import ScanTaskForm
    
    if request.method == 'POST':
        form = ScanTaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.status = 'pending'
            
            # 计算目标数量（交换机ARP类型特殊处理）
            if task.task_type == 'switch_arp':
                task.total_targets = 1  # 交换机设备本身作为目标
                task.target_type = 'switch'
            else:
                target_ips = task.get_target_ips()
                task.total_targets = len(target_ips)
            
            task.save()
            
            # 写入操作日志
            from common.logger import log_operation
            log_operation(
                user=request.user,
                module='IPAM-探测',
                operation_type='创建',
                obj_type=task.name,
                new_value=f'创建{task.get_task_type_display()}任务，目标数: {task.total_targets}'
            )
            
            messages.success(request, f"扫描任务「{task.name}」已创建，共 {task.total_targets} 个目标")
            return redirect('ipam:scan_detail', pk=task.pk)
    else:
        initial = {}
        subnet_id = request.GET.get('subnet')
        if subnet_id:
            try:
                subnet = Subnet.objects.get(pk=subnet_id)
                initial['target_type'] = 'subnet'
                initial['subnet'] = subnet.pk
            except Subnet.DoesNotExist:
                pass
        
        form = ScanTaskForm(initial=initial)
    
    return render(request, 'ipam/scan/create.html', {'form': form})


@login_required
def scan_task_detail(request, pk):
    """扫描任务详情页"""
    task = get_object_or_404(ScanTask, pk=pk)
    
    # 先获取QuerySet进行筛选
    results = task.results.all()

    # 统计信息（基于全部结果）
    stats = {
        'online': task.online_count,
        'offline': task.offline_count,
        'new_hosts': results.filter(is_new_host=True).count(),
        'conflicts': results.filter(status_conflict=True).count(),
    }

    # 筛选参数
    filter_status = request.GET.get('status', '')
    search_ip = request.GET.get('q', '')

    if filter_status:
        if filter_status == 'online':
            results = results.filter(is_online=True)
        elif filter_status == 'offline':
            results = results.filter(is_online=False)
        elif filter_status == 'new':
            results = results.filter(is_new_host=True)
        elif filter_status == 'conflict':
            results = results.filter(status_conflict=True)

    if search_ip:
        results = results.filter(ip_address__icontains=search_ip)

    # 筛选完成后转为list，按IP数值排序（确保 1.1.1.2 排在 1.1.1.10 前面）
    import ipaddress
    results_list = list(results)
    results_list.sort(key=lambda r: int(ipaddress.ip_address(r.ip_address)))
    results = results_list
    
    context = {
        'task': task,
        'results': results,
        'stats': stats,
        'filter_status': filter_status,
        'search_ip': search_ip,
    }
    return render(request, 'ipam/scan/detail.html', context)


@login_required
@require_POST
def execute_scan(request, pk):
    """
    执行扫描任务 (异步执行)
    在后台线程中运行扫描，前端通过AJAX轮询获取进度
    """
    task = get_object_or_404(ScanTask, pk=pk)
    
    if task.status == 'running':
        return JsonResponse({'success': False, 'error': '任务已在执行中'})
    
    # 启动后台线程执行扫描
    thread = threading.Thread(target=_run_scan_task, args=(task.pk,))
    thread.daemon = True
    thread.start()
    
    return JsonResponse({
        'success': True,
        'message': '扫描任务已启动',
        'task_id': task.pk
    })


def _run_scan_task(task_pk):
    """在后台线程中执行扫描任务 - 分阶段执行：Ping检测->端口扫描->结果入库 / 交换机ARP获取"""
    from django.core.cache import cache
    
    task = ScanTask.objects.get(pk=task_pk)
    task.status = 'running'
    task.started_at = timezone.now()
    task.save(update_fields=['status', 'started_at'])
    
    _running_tasks[task_pk] = {'status': 'running'}
    
    try:
        # ========== 交换机 ARP 获取（独立流程） ==========
        if task.task_type == 'switch_arp':
            return _run_switch_arp_scan(task, task_pk)

        # ========== 原有扫描流程 ==========
        target_ips = task.get_target_ips()
        task.total_targets = len(target_ips)
        task.save(update_fields=['total_targets'])
        
        ports = None
        if task.ports and task.task_type in ('port', 'full'):
            ports = PortScanner.parse_ports(task.ports)
        
        scanner = NetworkScanner(
            ping_count=task.ping_count,
            ping_timeout=task.ping_timeout,
        )
        
        def progress_callback(current, total, message=None):
            task.scanned_count = current
            task.save(update_fields=['scanned_count'])
            cache.set(f'scan_progress_{task_pk}', {
                'current': current,
                'total': total,
                'message': message or '',
            }, timeout=300)
        
        scan_results = scanner.subnet_scan(
            ips=target_ips,
            task_type=task.task_type,
            ports=ports,
            callback=progress_callback,
        )
        
        online_count = 0
        offline_count = 0
        
        for host_result in scan_results:
            result_obj, created = ScanResult.objects.update_or_create(
                task=task,
                ip_address=host_result.ip,
                defaults={
                    'is_online': host_result.is_online,
                    'ping_success': host_result.ping.success if host_result.ping else False,
                    'ping_avg_time': host_result.ping.avg_time if host_result.ping else None,
                    'ping_min_time': host_result.ping.min_time if host_result.ping else None,
                    'ping_max_time': host_result.ping.max_time if host_result.ping else None,
                    'packet_loss': host_result.ping.packet_loss if host_result.ping else 100.0,
                    'ttl': host_result.ping.ttl if host_result.ping else None,
                    'reverse_dns': host_result.reverse_dns,
                    'open_ports': {
                        str(p): {'state': r.state, 'service': r.service, 'banner': r.banner}
                        for p, r in host_result.ports.items()
                    } if host_result.ports else {},
                    'mac_address': host_result.mac_address,
                    'vendor': host_result.vendor,
                }
            )
            
            ip_records = IPAddress.objects.filter(ip_address=host_result.ip)
            if host_result.is_online and not ip_records.exists():
                result_obj.is_new_host = True
            else:
                result_obj.is_new_host = False
            
            allocated_record = ip_records.filter(status='allocated').first()
            
            result_obj.save()
            
            if host_result.is_online:
                online_count += 1
                
                ProbeHistory.objects.create(
                    ip_address=host_result.ip,
                    subnet=task.subnet,
                    is_online=True,
                    ping_time=host_result.ping.avg_time if host_result.ping else None,
                    mac_address=host_result.mac_address,
                    open_ports=list(host_result.ports.keys()) if host_result.ports else [],
                    source='task',
                    task=task,
                )
            else:
                offline_count += 1
        
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.scanned_count = len(scan_results)
        task.online_count = online_count
        task.offline_count = offline_count
        task.save()
        
        _running_tasks[task_pk] = {'status': 'completed'}
        
        cache.delete(f'scan_progress_{task_pk}')
        
    except Exception as e:
        task.status = 'failed'
        task.notes = str(e)
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'notes', 'completed_at'])
        
        _running_tasks[task_pk] = {'status': 'failed', 'error': str(e)}


def _run_switch_arp_scan(task, task_pk):
    """执行交换机ARP获取任务"""
    from django.core.cache import cache
    
    switch = task.switch_device
    if not switch:
        raise ValueError('未选择交换机设备')
    
    cache.set(f'scan_progress_{task_pk}', {
        'current': 0, 'total': 1,
        'message': f'正在连接 {switch.name} ({switch.ip_address}) ...',
    }, timeout=300)
    
    scanner = SwitchARPScanner(timeout=30)
    
    try:
        scan_results = scanner.fetch_arp(switch)
        
        # 更新交换机状态
        switch.last_success_at = timezone.now()
        switch.last_error = ''
        switch.save(update_fields=['last_success_at', 'last_error'])
        
        online_count = 0
        for i, host_result in enumerate(scan_results):
            cache.set(f'scan_progress_{task_pk}', {
                'current': i + 1, 'total': len(scan_results),
                'message': f'处理: {host_result.ip} ({host_result.mac_address})',
            }, timeout=300)
            
            result_obj, created = ScanResult.objects.update_or_create(
                task=task,
                ip_address=host_result.ip,
                defaults={
                    'is_online': True,
                    'ping_success': True,
                    'mac_address': host_result.mac_address,
                    'vendor': host_result.vendor,
                    'reverse_dns': host_result.reverse_dns or '',
                    'open_ports': {},
                }
            )
            
            ip_records = IPAddress.objects.filter(ip_address=host_result.ip)
            if not ip_records.exists():
                result_obj.is_new_host = True
            else:
                result_obj.is_new_host = False
            
            result_obj.save()
            online_count += 1
            
            ProbeHistory.objects.create(
                ip_address=host_result.ip,
                subnet=switch.subnet,
                is_online=True,
                mac_address=host_result.mac_address,
                source='task',
                task=task,
            )
        
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.total_targets = len(scan_results)
        task.scanned_count = len(scan_results)
        task.online_count = online_count
        task.offline_count = 0
        task.save()
        
        _running_tasks[task_pk] = {'status': 'completed'}
        cache.delete(f'scan_progress_{task_pk}')
        
    except Exception as e:
        switch.last_error = str(e)[:500]
        switch.save(update_fields=['last_error'])
        
        task.status = 'failed'
        task.notes = str(e)
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'notes', 'completed_at'])
        
        _running_tasks[task_pk] = {'status': 'failed', 'error': str(e)}


@login_required
@require_GET
def get_scan_progress(request, pk):
    """获取扫描进度 (AJAX)"""
    from django.core.cache import cache
    
    progress = cache.get(f'scan_progress_{pk}')
    task = get_object_or_404(ScanTask, pk=pk)
    
    return JsonResponse({
        'status': task.status,
        'scanned': task.scanned_count,
        'total': task.total_targets,
        'online': task.online_count,
        'offline': task.offline_count,
        'progress': progress,
        'started_at': task.started_at.isoformat() if task.started_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
    })


@login_required
@require_POST
def cancel_scan(request, pk):
    """取消扫描任务"""
    task = get_object_or_404(ScanTask, pk=pk)
    
    if task.status == 'running':
        task.status = 'cancelled'
        task.notes = '用户取消'
        task.completed_at = timezone.now()
        task.save()
        
        _running_tasks[task.pk] = {'status': 'cancelled'}
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': '该任务不在执行状态'})


@login_required
def quick_ping(request):
    """快速Ping探测单个IP (AJAX) - 返回在线状态、延迟、丢包率、TTL"""
    ip = request.GET.get('ip', '')
    if not ip:
        return JsonResponse({'error': '请提供IP地址'}, status=400)
    
    # 验证IP格式
    import ipaddress
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return JsonResponse({'error': '无效的IP地址格式'}, status=400)
    
    # 执行Ping
    from ipam.scanner import PingScanner
    scanner = PingScanner(count=3, timeout=1.0)
    result = scanner.ping(ip)
    
    # 记录探测历史 - 保留每次探测结果供历史查询
    ProbeHistory.objects.create(
        ip_address=ip,
        is_online=result.success,
        ping_time=result.avg_time,
        source='manual',
    )
    
    return JsonResponse({
        'success': True,
        'is_online': result.success,
        'avg_time': round(result.avg_time, 2) if result.avg_time else None,
        'packet_loss': result.packet_loss,
        'ttl': result.ttl,
        'error': result.error,
    })


@login_required
def quick_port_scan(request):
    """快速端口扫描单个IP (AJAX) - 返回开放端口列表和服务信息"""
    ip = request.GET.get('ip', '')
    ports_str = request.GET.get('ports', '22,80,443')
    
    if not ip:
        return JsonResponse({'error': '请提供IP地址'}, status=400)
    
    # 解析端口
    ports = PortScanner.parse_ports(ports_str)
    if not ports:
        return JsonResponse({'error': '无效的端口列表'}, status=400)
    
    # 限制最大端口数
    if len(ports) > 1000:
        return JsonResponse({'error': '单次最多扫描1000个端口'}, status=400)
    
    # 执行扫描
    scanner = PortScanner(timeout=2.0)
    results = scanner.scan_host(ip, ports)
    
    open_ports = []
    for port, result in results.items():
        if result.state == 'open':
            open_ports.append({
                'port': port,
                'state': result.state,
                'service': result.service,
                'banner': result.banner[:100] if result.banner else '',
            })
    
    # 记录探测历史 - 能进行端口扫描说明主机在线
    ProbeHistory.objects.create(
        ip_address=ip,
        is_online=True,  # 能进行端口扫描说明主机在线
        open_ports=[p for p, r in results.items() if r.state == 'open'],
        source='manual',
    )
    
    return JsonResponse({
        'success': True,
        'ip': ip,
        'total_scanned': len(results),
        'open_count': len(open_ports),
        'ports': sorted(open_ports, key=lambda x: x['port']),
    })


@login_required
def probe_history(request):
    """探测历史记录 - 支持按IP和来源筛选，最多展示100条"""
    ip_filter = request.GET.get('ip', '')
    source_filter = request.GET.get('source', '')
    
    queryset = ProbeHistory.objects.all()
    
    if ip_filter:
        queryset = queryset.filter(ip_address__icontains=ip_filter)
    if source_filter:
        queryset = queryset.filter(source=source_filter)
    
    history = queryset.select_related('task', 'subnet')[:100]
    
    context = {
        'history': history,
        'ip_filter': ip_filter,
        'source_filter': source_filter,
    }
    return render(request, 'ipam/scan/history.html', context)


@login_required
def discovery_rules(request):
    """自动发现规则管理页面 - 展示所有发现规则及其关联子网"""
    rules = DiscoveryRule.objects.all().select_related('subnet')
    
    context = {
        'rules': rules,
    }
    return render(request, 'ipam/scan/rules.html', context)


@login_required
@require_POST
def delete_scan_task(request, pk):
    """删除扫描任务及其结果"""
    task = get_object_or_404(ScanTask, pk=pk)
    
    task_name = task.name
    
    # 删除关联结果
    task.results.all().delete()
    
    # 写入日志
    from common.logger import log_operation
    log_operation(
        user=request.user,
        module='IPAM-探测',
        operation_type='删除',
        obj_type=f'扫描任务: {task_name}',
    )
    
    task.delete()
    
    messages.success(request, f"扫描任务「{task_name}」已删除")
    return redirect('ipam:scan_index')


@login_required
def export_scan_results(request, pk):
    """导出扫描结果为CSV"""
    import csv
    from django.http import StreamingResponse
    
    task = get_object_or_404(ScanTask, pk=pk)
    results = task.results.all().order_by('ip_address')
    
    def generate_csv():
        yield ','.join(['IP地址', '在线状态', '延迟(ms)', '丢包率(%)', 
                       'MAC地址', '厂商', '反解域名', '开放端口', '是否新发现']) + '\n'
        
        for r in results:
            open_ports = ';'.join([f"{p}:{info.get('service','')}" 
                                   for p, info in r.open_ports.items() 
                                   if info.get('state') == 'open'])
            yield ','.join([
                r.ip_address,
                '在线' if r.is_online else '离线',
                str(round(r.ping_avg_time, 2)) if r.ping_avg_time else '',
                str(r.packet_loss),
                r.mac_address,
                r.vendor,
                r.reverse_dns,
                open_ports,
                '是' if r.is_new_host else '否'
            ]) + '\n'
    
    response = StreamingResponse(generate_csv(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="scan_results_{task.name}.csv"'
    return response


@login_required
@require_POST
def quick_allocate_ip(request):
    """从扫描结果页面快速分配IP (AJAX)"""
    ip_addr = request.POST.get('ip_address', '')
    subnet_id = request.POST.get('subnet_id', '')
    device_name = request.POST.get('device_name', '')
    owner = request.POST.get('owner', '')
    department = request.POST.get('department', '')
    mac_address = request.POST.get('mac_address', '')
    
    if not ip_addr:
        return JsonResponse({'success': False, 'error': 'IP地址不能为空'}, status=400)
    
    # 验证IP格式
    import ipaddress
    try:
        ipaddress.ip_address(ip_addr)
    except ValueError:
        return JsonResponse({'success': False, 'error': '无效的IP地址格式'}, status=400)

    # 查找或创建IPAddress记录
    try:
        if subnet_id:
            subnet = Subnet.objects.get(pk=subnet_id)
        else:
            # 尝试根据IP自动匹配子网
            subnet = None
            for sn in Subnet.objects.all():
                try:
                    network = ipaddress.ip_network(sn.cidr, strict=False)
                    if ipaddress.ip_address(ip_addr) in network:
                        subnet = sn
                        break
                except ValueError:
                    continue
            
            if not subnet:
                return JsonResponse({'success': False, 'error': '无法确定所属子网，请手动选择'}, status=400)
        
        ip_obj, created = IPAddress.objects.update_or_create(
            ip_address=ip_addr,
            subnet=subnet,
            defaults={
                'status': 'allocated',
                'device_name': device_name,
                'owner': owner,
                'department': department,
                'mac_address': mac_address,
                'created_by': request.user,
            }
        )
        
        action = '创建并分配' if created else '分配'
        
        from common.logger import log_operation
        log_operation(
            user=request.user,
            module='IPAM-探测',
            operation_type=f'快速{action}',
            obj_type='IP地址',
            new_value=f'{ip_addr} -> {device_name or owner or "已分配"}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'IP {ip_addr} {action}成功',
            'ip_id': ip_obj.pk,
        })
    
    except Subnet.DoesNotExist:
        return JsonResponse({'success': False, 'error': '子网不存在'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ========== 交换机设备管理 ==========

@login_required
def switch_list(request):
    """交换机设备列表"""
    switches = SwitchDevice.objects.all().order_by('name')
    context = {
        'switches': switches,
        'page_title': '交换机设备管理',
    }
    return render(request, 'ipam/scan/switch_list.html', context)


@login_required
def switch_create(request):
    """新增交换机设备"""
    from .scan_forms import SwitchDeviceForm
    
    if request.method == 'POST':
        form = SwitchDeviceForm(request.POST)
        if form.is_valid():
            switch = form.save()
            messages.success(request, f'交换机「{switch.name}」已添加')
            log_operation(
                user=request.user,
                module='IPAM-探测',
                operation_type='新增',
                obj_type='交换机设备',
                new_value=str(switch),
            )
            return redirect('ipam:switch_list')
    else:
        form = SwitchDeviceForm()
    
    return render(request, 'ipam/scan/switch_form.html', {'form': form})


@login_required
def switch_update(request, pk):
    """编辑交换机设备"""
    switch = get_object_or_404(SwitchDevice, pk=pk)
    from .scan_forms import SwitchDeviceForm
    
    if request.method == 'POST':
        form = SwitchDeviceForm(request.POST, instance=switch)
        if form.is_valid():
            sw = form.save()
            messages.success(request, f'交换机「{sw.name}」已更新')
            log_operation(
                user=request.user,
                module='IPAM-探测',
                operation_type='编辑',
                obj_type='交换机设备',
                new_value=str(sw),
            )
            return redirect('ipam:switch_list')
    else:
        form = SwitchDeviceForm(instance=switch)
    
    return render(request, 'ipam/scan/switch_form.html', {'form': form, 'switch': switch})


@login_required
@require_POST
def switch_delete(request, pk):
    """删除交换机设备"""
    switch = get_object_or_404(SwitchDevice, pk=pk)
    name = switch.name
    switch.delete()
    messages.success(request, f'交换机「{name}」已删除')
    log_operation(
        user=request.user,
        module='IPAM-探测',
        operation_type='删除',
        obj_type=f'交换机设备: {name}',
    )
    return redirect('ipam:switch_list')


@login_required
def switch_test_connection(request, pk):
    """测试交换机SSH连接 (AJAX)"""
    switch = get_object_or_404(SwitchDevice, pk=pk)
    
    success, msg = SwitchARPScanner.test_connection(switch)
    
    if success:
        switch.last_success_at = timezone.now()
        switch.last_error = ''
        switch.save(update_fields=['last_success_at', 'last_error'])
        return JsonResponse({'success': True, 'message': msg})
    else:
        switch.last_error = msg[:500]
        switch.save(update_fields=['last_error'])
        return JsonResponse({'success': False, 'error': msg}, status=400)


@login_required
def live_topology(request):
    """实时网络拓扑展示 - 基于最近扫描数据按子网分组展示在线主机"""
    # 获取最近的在线主机（保持QuerySet，不提前切片）
    recent_probes_qs = ProbeHistory.objects.filter(is_online=True).order_by('-probed_at')
    
    # 按子网分组统计
    subnets_data = []
    subnets = Subnet.objects.annotate(ip_count=Count('ip_addresses')).all()
    
    for subnet in subnets:
        online_ips = recent_probes_qs.filter(subnet=subnet).values_list('ip_address', flat=True).distinct()
        subnets_data.append({
            'subnet': subnet,
            'online_count': online_ips.count(),
            'total_count': subnet.ip_addresses.count() if hasattr(subnet, 'ip_addresses') else 0,
        })
    
    # 最后才切片
    recent_probes = list(recent_probes_qs[:50])
    
    context = {
        'subnets_data': subnets_data,
        'recent_probes': recent_probes,
    }
    return render(request, 'ipam/scan/topology.html', context)
