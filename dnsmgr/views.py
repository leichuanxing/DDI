from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.db import models
from django.http import JsonResponse
import socket
import time
import json
from .models import DNSZone, DNSRecord, DNSSettings, DNSQueryLog, ProbeTask
from .forms import DNSZoneForm, DNSRecordForm, DNSRecordSearchForm, DNSSettingsForm, DNSQueryLogSearchForm
from common.logger import log_operation


# ========== DNS区域管理 ==========
@method_decorator([login_required], name='dispatch')
class ZoneListView(ListView):
    model = DNSZone
    template_name = 'dnsmgr/zone_list.html'
    context_object_name = 'zones'


@method_decorator([login_required], name='dispatch')
class ZoneDetailView(DetailView):
    model = DNSZone
    template_name = 'dnsmgr/zone_detail.html'
    context_object_name = 'zone'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        zone = self.object
        
        # 获取该区域的记录
        records = zone.records.all()
        
        # 筛选
        record_type = self.request.GET.get('type', '')
        search = self.request.GET.get('search', '')
        status = self.request.GET.get('status', '')
        
        if record_type:
            records = records.filter(record_type=record_type)
        if status:
            records = records.filter(status=status)
        if search:
            records = records.filter(name__icontains=search) | \
                       records.filter(value__icontains=search)
        
        context['records'] = records
        context['search'] = search
        context['type_filter'] = record_type
        context['status_filter'] = status
        context['record_types'] = DNSRecord.RECORD_TYPE_CHOICES

        # 探测任务列表（用于新增记录模态框）
        context['probe_tasks'] = ProbeTask.objects.filter(
            created_by=self.request.user
        ).order_by('-created_at')

        # 为每条记录附加探测状态（基于关联的探测任务最新结果）
        probe_ports = set(r.probe_port for r in records if r.probe_port)
        if probe_ports:
            from django.db.models import Max
            probe_tasks = ProbeTask.objects.filter(
                port__in=probe_ports,
                created_by=self.request.user,
                status='running',
            ).values('port').annotate(last_status=Max('last_status'))
            port_status = {pt['port']: pt['last_status'] for pt in probe_tasks}

            # 获取探测任务名称+目标（按端口匹配，用于显示关联任务信息）
            pt_name_map = {}
            for pt in ProbeTask.objects.filter(port__in=probe_ports, created_by=self.request.user):
                if pt.port not in pt_name_map:  # 每个端口取第一个
                    pt_name_map[pt.port] = {'name': pt.name, 'target': pt.target}
        else:
            port_status = {}
            pt_name_map = {}

        # 给记录对象附上探测状态属性
        for r in records:
            r.probe_last_status = port_status.get(r.probe_port, '')
            if r.probe_port and r.probe_port in pt_name_map:
                info = pt_name_map[r.probe_port]
                r.probe_task_name = info['name']
                r.probe_task_target = info['target']

            # 根据探测任务最新状态，计算动态展示的状态
            if r.status == 'disabled':
                r.display_status = 'disabled'
            elif r.probe_port and r.probe_last_status == 'reachable':
                r.display_status = 'enabled'
            elif r.probe_port and r.probe_last_status in ('timeout', 'unreachable', 'refused', 'dns_fail', 'error'):
                r.display_status = 'invalid'
            elif r.probe_port and not r.probe_last_status:
                r.display_status = r.status  # 探测中，保持原状态
            else:
                r.display_status = r.status
        
        return context


@method_decorator([login_required], name='dispatch')
class ZoneCreateView(CreateView):
    model = DNSZone
    form_class = DNSZoneForm
    template_name = 'dnsmgr/zone_form.html'
    success_url = reverse_lazy('dnsmgr:zone_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'DNS区域 {form.instance.name} 创建成功')
        log_operation(self.request.user, '新增', 'dns', 'zone', '', form.instance.name)
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class ZoneUpdateView(UpdateView):
    model = DNSZone
    form_class = DNSZoneForm
    template_name = 'dnsmgr/zone_form.html'
    success_url = reverse_lazy('dnsmgr:zone_list')


@method_decorator([login_required], name='dispatch')
class ZoneDeleteView(DeleteView):
    model = DNSZone
    template_name = 'dnsmgr/confirm_delete.html'
    success_url = reverse_lazy('dnsmgr:zone_list')


# ========== DNS记录管理 ==========
@method_decorator([login_required], name='dispatch')
class RecordListView(ListView):
    model = DNSRecord
    template_name = 'dnsmgr/record_list.html'
    context_object_name = 'records'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('zone')
        
        form = DNSRecordSearchForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            record_type = form.cleaned_data.get('record_type')
            zone = form.cleaned_data.get('zone')
            status = form.cleaned_data.get('status')
            
            if search:
                queryset = queryset.filter(name__icontains=search) | \
                           queryset.filter(value__icontains=search)
            if record_type:
                queryset = queryset.filter(record_type=record_type)
            if zone:
                queryset = queryset.filter(zone=zone)
            if status:
                queryset = queryset.filter(status=status)
        
        return queryset.order_by('zone__name', 'name')


@method_decorator([login_required], name='dispatch')
class RecordCreateView(CreateView):
    model = DNSRecord
    form_class = DNSRecordForm
    template_name = 'dnsmgr/record_form.html'

    def get_success_url(self):
        return reverse('dnsmgr:zone_detail', kwargs={'pk': self.object.zone.pk})
    
    def get_initial(self):
        initial = super().get_initial()
        zone_id = self.request.GET.get('zone')
        if zone_id:
            initial['zone'] = zone_id
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['probe_tasks'] = ProbeTask.objects.filter(
            created_by=self.request.user
        ).order_by('-created_at')
        return ctx

    def form_valid(self, form):
        # 先保存记录
        response = super().form_valid(form)
        record = self.object

        # 如果设置了探测端口，自动探测目标
        probe_port = form.cleaned_data.get('probe_port')
        if probe_port:
            try:
                target_ip = self._get_probe_target_ip(record)
                if target_ip:
                    try:
                        probe_result = _probe_single(target_ip, int(probe_port), timeout=3)
                        log_operation(self.request.user, '探测', 'dns', 'record_probe', '',
                                     f"{target_ip}:{probe_port} -> {probe_result['status']}")

                        if probe_result['status'] == 'reachable':
                            if record.status != 'disabled':
                                record.status = 'enabled'
                                record.save()
                                messages.success(self.request,
                                    f'DNS记录 {record.name} 创建成功！服务探测 <span class="text-success">可达</span> '
                                    f'({target_ip}:{probe_port} 延迟{probe_result["latency_ms"]}ms) - DNS已标记为有效')
                            else:
                                messages.success(self.request,
                                    f'DNS记录 {record.name} 创建成功！服务探测 <span class="text-success">可达</span> '
                                    f'({target_ip}:{probe_port} 延迟{probe_result["latency_ms"]}ms)')
                        else:
                            record.status = 'invalid'
                            record.save()
                            messages.warning(self.request,
                                f'DNS记录 {record.name} 已创建，但服务探测 <span class="text-danger">{probe_result["status"].upper()}</span> '
                                f'({target_ip}:{probe_port}: {probe_result["message"]}) - DNS已自动标记为<span class="text-danger">无效</span>')
                    except Exception as e:
                        messages.info(self.request,
                            f'DNS记录 {record.name} 创建成功，但服务探测执行失败: {str(e)[:80]}')
                else:
                    messages.success(self.request, f'DNS记录 {record.name} 创建成功')
            except Exception as e:
                # 探测相关任何异常都不影响记录保存
                messages.success(self.request, f'DNS记录 {record.name} 创建成功')
                messages.info(self.request, f'服务探测跳过（{str(e)[:60]}）')
        else:
            messages.success(self.request, f'DNS记录 {record.name} 创建成功')

        log_operation(self.request.user, '新增', 'dns', 'record', '', str(record))
        return response

    def _get_probe_target_ip(self, record):
        """根据记录类型获取探测目标IP"""
        if record.record_type == 'A' or record.record_type == 'AAAA':
            return record.value.strip() if record.value else None
        return None


@method_decorator([login_required], name='dispatch')
class RecordUpdateView(UpdateView):
    model = DNSRecord
    form_class = DNSRecordForm
    template_name = 'dnsmgr/record_form.html'

    def get_success_url(self):
        return reverse('dnsmgr:zone_detail', kwargs={'pk': self.object.zone.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['probe_tasks'] = ProbeTask.objects.filter(
            created_by=self.request.user
        ).order_by('-created_at')
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'DNS记录 {self.object.name} 已更新')
        log_operation(self.request.user, '修改', 'dns', 'record', '', str(self.object))
        return response


@method_decorator([login_required], name='dispatch')
class RecordDeleteView(DeleteView):
    model = DNSRecord
    template_name = 'dnsmgr/confirm_delete.html'
    success_url = reverse_lazy('dnsmgr:record_list')


@login_required
def toggle_record_status(request, pk):
    """启用/禁用DNS记录"""
    record = get_object_or_404(DNSRecord, pk=pk)
    old_status = record.get_status_display()
    
    if record.status == 'enabled':
        record.disable()
        messages.success(request, f'DNS记录 {record.name} 已禁用')
    else:
        record.enable()
        messages.success(request, f'DNS记录 {record.name} 已启用')
    
    log_operation(request.user, '修改状态', 'dns', 'record', old_status, 
                 f"{record.name}->{record.get_status_display()}")
    return redirect('dnsmgr:zone_detail', pk=record.zone.pk)


# ========== DNS服务管理 ==========
@login_required
def dns_service(request):
    """DNS服务管理页面 - 配置、启动、停止"""
    from .dns_server import get_dns_server

    dns_server = get_dns_server()
    settings_obj = DNSSettings.get_settings()

    if request.method == 'POST':
        action = request.POST.get('action')

        # === 启动/停止服务 ===
        if action == 'start':
            success, msg = dns_server.start()
            messages.success(request, msg) if success else messages.error(request, msg)
            log_operation(request.user, '启动', 'dns', 'service', '', msg)

        elif action == 'stop':
            success, msg = dns_server.stop()
            messages.success(request, msg) if success else messages.error(request, msg)
            log_operation(request.user, '停止', 'dns', 'service', '', msg)

        # === 保存配置 ===
        elif action == 'save_settings':
            form = DNSSettingsForm(request.POST, instance=settings_obj)
            if form.is_valid():
                form.save()
                messages.success(request, 'DNS配置已保存')
                log_operation(request.user, '配置', 'dns', 'settings', '',
                             f"转发器={form.cleaned_data['forwarders']}")
                # 如果服务在运行，提示需要重启
                if dns_server.is_running:
                    messages.info(request, '配置已保存，重启DNS服务后生效')
            else:
                messages.error(request, '配置校验失败，请检查输入')

        return redirect('dnsmgr:dns_service')

    context = {
        'server': dns_server,
        'status': dns_server.get_status(),
        'settings': settings_obj,
        'form': DNSSettingsForm(instance=settings_obj),
    }

    # 统计本地区域和记录数
    try:
        context['zone_count'] = DNSZone.objects.count()
        context['record_count'] = DNSRecord.objects.count()
    except:
        context['zone_count'] = 0
        context['record_count'] = 0

    return render(request, 'dnsmgr/service.html', context)


# ========== DNS解析日志查询 ==========
@login_required
def query_log(request):
    """DNS解析记录查询 - 最多显示10000条"""
    queryset = DNSQueryLog.objects.all()
    
    # 搜索表单
    search_form = DNSQueryLogSearchForm(request.GET)
    if request.GET and search_form.is_valid():
        search = search_form.cleaned_data.get('search', '')
        query_type = search_form.cleaned_data.get('query_type', '')
        result_source = search_form.cleaned_data.get('result_source', '')
        
        if search:
            queryset = queryset.filter(
                models.Q(query_name__icontains=search) | 
                models.Q(client_ip__icontains=search)
            )
        if query_type:
            queryset = queryset.filter(query_type=query_type)
        if result_source:
            queryset = queryset.filter(result_source=result_source)

    # 限制最大10000条（分页每页50条）
    total_count = queryset.count()
    
    from django.core.paginator import Paginator
    paginator = Paginator(queryset[:10000], per_page=50)  # 硬截断10000条
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except Exception:
        page_obj = paginator.page(1)
    
    # 统计数据
    stats_list = []
    total_logs = DNSQueryLog.objects.count()
    for src, label in DNSQueryLog.SOURCE_CHOICES:
        cnt = min(DNSQueryLog.objects.filter(result_source=src).count(), 10000)
        stats_list.append({'key': src, 'label': label, 'count': cnt})
    
    # 预计算分页可见页码（当前页±2，加上首页末页）
    def get_visible_pages(current_page_num, total_pages):
        """生成智能分页可见页码列表"""
        result = set()
        # 当前页附近
        for p in range(max(1, current_page_num - 2), min(total_pages + 1, current_page_num + 3)):
            result.add(p)
        # 前后各2页
        result.add(1)
        result.add(2)
        if total_pages >= 2:
            result.add(total_pages)
        if total_pages >= 3:
            result.add(total_pages - 1)
        return sorted(result)

    visible_pages = get_visible_pages(page_obj.number, paginator.num_pages)

    context = {
        'page_obj': page_obj,
        'logs': page_obj,
        'is_paginated': True,
        'search_form': search_form,
        'total_count': min(total_count, 10000),
        'total_stored': total_logs,
        'stats_list': stats_list,
        'visible_pages': visible_pages,
    }
    return render(request, 'dnsmgr/query_log.html', context)


@login_required
def clear_query_log(request):
    """清空DNS解析日志"""
    if request.method == 'POST':
        count = DNSQueryLog.objects.count()
        DNSQueryLog.objects.all().delete()
        messages.success(request, f'已清空 {count} 条解析日志')
        log_operation(request.user, '清空', 'dns', 'query_log', '', f'清空{count}条')
    return redirect('dnsmgr:query_log')


# ========== DNS解析测试 ==========
@login_required
def dns_resolve_test(request):
    """智能DNS解析测试 - 测试记录是否能正确解析"""
    if request.method != 'GET':
        return JsonResponse({'error': '仅支持GET请求'}, status=405)

    record_id = request.GET.get('record_id')
    domain = request.GET.get('domain', '').strip()
    record_type = request.GET.get('type', 'A').strip().upper()
    test_dns_server = request.GET.get('dns_server', '127.0.0.1').strip()

    # 确定要查询的域名和类型
    if record_id:
        try:
            record = DNSRecord.objects.select_related('zone').get(pk=int(record_id))
            domain = record.get_fqdn()
            record_type = record.record_type
        except (DNSRecord.DoesNotExist, ValueError):
            return JsonResponse({'error': '记录不存在'}, status=404)

    if not domain:
        return JsonResponse({'error': '请指定域名或记录ID'}, status=400)

    # 获取当前DNS服务状态
    from .dns_server import get_dns_server
    dns_server = get_dns_server()

    result = {
        'domain': domain,
        'type': record_type,
        'record_id': record_id or None,
        'dns_service_running': dns_server.is_running,
        'test_results': [],
        'effective': False,
        'effective_reason': '',
    }

    qtype_map = {'A': 1, 'AAAA': 28, 'CNAME': 5, 'MX': 15, 'TXT': 16, 'NS': 2, 'PTR': 12}
    qtype_code = qtype_map.get(record_type, 1)

    # === 测试1: 通过本地DNS服务解析 ===
    if dns_server.is_running:
        local_result = _resolve_via_dns(domain, qtype_code, test_dns_server, timeout=3)
        local_result['source'] = '本地DNS服务'
        local_result['server'] = f'{test_dns_server}:{DNSSettings.get_settings().listen_port}'
        result['test_results'].append(local_result)

        # 判断记录是否生效
        if local_result['rcode'] == 0 and local_result['answers']:
            result['effective'] = True
            result['effective_reason'] = f"本地解析成功: {', '.join(local_result['answers'])}"
        elif local_result['rcode'] == 3:
            result['effective'] = False
            result['effective_reason'] = 'NXDOMAIN - 本地无此域名或记录未启用'

    # === 测试2: 通过系统DNS解析（对比） ===
    sys_result = _resolve_via_system_dns(domain, record_type)
    sys_result['source'] = '系统DNS'
    result['test_results'].append(sys_result)

    # 综合判断生效状态
    if not result['effective']:
        if sys_result['rcode'] == 0 and sys_result['answers']:
            # 系统DNS能解析但本地不行，说明本地没有这条记录或者没启用
            result['effective_reason'] = f"本地DNS未返回结果(可能记录禁用/不存在)，系统DNS可解析为: {', '.join(sys_result['answers'])}"
        elif dns_server.is_running:
            pass  # 已经设置了原因

    log_operation(request.user, '解析测试', 'dns', 'resolve_test', domain,
                  f"type={record_type}, effective={result['effective']}")

    return JsonResponse(result)


def _resolve_via_dns(domain, qtype_code, dns_server_ip='127.0.0.1', timeout=3):
    """通过指定DNS服务器执行DNS解析"""
    result = {
        'rcode': -1,
        'rcname': 'ERROR',
        'answers': [],
        'latency_ms': 0,
        'raw_response': None,
        'error': None,
    }

    import struct
    import random

    tid = random.randint(0, 65535)
    start = time.time()

    try:
        # 构造DNS查询包
        request_data = bytearray()
        request_data += struct.pack('!H', tid)          # Transaction ID
        request_data += struct.pack('!H', 0x0100)       # Flags: RD=1
        request_data += struct.pack('!HHHH', 1, 0, 0, 0)  # QD=1, AN=0, NS=0, AR=0

        # 编码域名
        for label in domain.rstrip('.').split('.'):
            encoded = label.encode('ascii')
            request_data += bytes([len(encoded)]) + encoded
        request_data += b'\x00'                          # End of name
        request_data += struct.pack('!HH', qtype_code, 1)  # QTYPE, QCLASS IN
        request_data = bytes(request_data)

        # 发送UDP查询
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(request_data, (dns_server_ip, 53))
        response, _ = sock.recvfrom(4096)
        sock.close()

        latency_ms = round((time.time() - start) * 1000, 1)
        result['latency_ms'] = latency_ms

        if len(response) < 12:
            result['error'] = '响应包过短'
            return result

        # 解析响应头
        resp_tid = struct.unpack('!H', response[0:2])[0]
        flags = struct.unpack('!H', response[2:4])[0]
        ancount = struct.unpack('!H', response[6:8])[0]
        rcode_val = flags & 0xF

        rcode_names = {0: 'NOERROR', 1: 'FORMERR', 2: 'SERVFAIL',
                       3: 'NXDOMAIN', 4: 'NOTIMP', 5: 'REFUSED'}
        result['rcode'] = rcode_val
        result['rcname'] = rcode_names.get(rcode_val, str(rcode_val))

        # 解析Answer部分提取IP/域名
        if ancount > 0 and rcode_val == 0:
            answers = _extract_answers_from_response(response, ancount, qtype_code)
            result['answers'] = answers

    except socket.timeout:
        result['rcode'] = -2
        result['rcname'] = 'TIMEOUT'
        result['error'] = f'查询超时 (>{timeout}s)'
        result['latency_ms'] = round(timeout * 1000, 1)
    except ConnectionRefusedError:
        result['rcode'] = -3
        result['rcname'] = 'REFUSED'
        result['error'] = 'DNS服务未运行或连接被拒绝'
    except Exception as e:
        result['error'] = str(e)[:120]

    return result


def _resolve_via_system_dns(domain, record_type='A'):
    """通过系统DNS（resolv.conf）进行解析对比"""
    result = {
        'rcode': -1,
        'rcname': 'ERROR',
        'answers': [],
        'latency_ms': 0,
        'error': None,
    }

    start = time.time()

    try:
        if record_type == 'A':
            addr_info = socket.getaddrinfo(domain, None, socket.AF_INET)
            ips = list(set(item[4][0] for item in addr_info))
            result['rcode'] = 0
            result['rcname'] = 'NOERROR'
            result['answers'] = ips[:10]
        elif record_type == 'AAAA':
            try:
                addr_info = socket.getaddrinfo(domain, None, socket.AF_INET6)
                ips = list(set(item[4][0] for item in addr_info))
                result['rcode'] = 0
                result['rcname'] = 'NOERROR'
                result['answers'] = ips[:10]
            except socket.gaierror:
                # AAAA可能没有，尝试A记录看域名是否存在
                try:
                    socket.getaddrinfo(domain, None, socket.AF_INET)
                    result['rcode'] = 0
                    result['rcname'] = 'NOERROR'
                    result['answers'] = ['(无AAAA记录)']
                except socket.gaierror:
                    result['rcode'] = 3
                    result['rcname'] = 'NXDOMAIN'
        else:
            # 对于非A/AAAA类型，用通用方式
            addr_info = socket.getaddrinfo(domain, None)
            ips = list(set(item[4][0] for item in addr_info))
            result['rcode'] = 0
            result['rcname'] = 'NOERROR'
            result['answers'] = ips[:10] if ips else [f'(类型{record_type}需通过DNS工具验证)']

        result['latency_ms'] = round((time.time() - start) * 1000, 1)

    except socket.gaierror as e:
        result['rcode'] = 3
        result['rcname'] = 'NXDOMAIN'
        result['error'] = f'域名无法解析: {str(e)[:80]}'
        result['latency_ms'] = round((time.time() - start) * 1000, 1)
    except Exception as e:
        result['error'] = str(e)[:120]

    return result


def _extract_answers_from_response(resp_bytes, ancount, expected_qtype):
    """从DNS响应中提取答案"""
    import struct

    answers = []
    pos = 12  # Skip header

    # Skip question section (1 question)
    for _ in range(1):
        while pos < len(resp_bytes) and resp_bytes[pos] != 0:
            if (resp_bytes[pos] & 0xC0) == 0xC0:
                pos += 2
                break
            pos += 1 + resp_bytes[pos]
        else:
            pos += 1  # skip \x00
        pos += 4   # QTYPE + QCLASS

    # Parse answer records
    reverse_qtype = {1: 'A', 28: 'AAAA', 5: 'CNAME', 15: 'MX', 16: 'TXT', 2: 'NS', 12: 'PTR'}

    for _ in range(min(ancount, 20)):
        if pos + 12 > len(resp_bytes):
            break

        # Name (with pointer support)
        if (resp_bytes[pos] & 0xC0) == 0xC0:
            pos += 2
        else:
            while pos < len(resp_bytes) and resp_bytes[pos] != 0:
                pos += 1 + resp_bytes[pos]
            pos += 1

        if pos + 10 > len(resp_bytes):
            break

        rtype = struct.unpack('!H', resp_bytes[pos:pos+2])[0]; pos += 2
        pos += 2  # class
        pos += 4  # ttl
        rdlen = struct.unpack('!H', resp_bytes[pos:pos+2])[0]; pos += 2

        if pos + rdlen > len(resp_bytes):
            break

        rdata = resp_bytes[pos:pos+rdlen]; pos += rdlen

        # Extract readable data based on type
        if rtype == 1 and len(rdata) >= 4:  # A
            answers.append('.'.join(str(b) for b in rdata[:4]))
        elif rtype == 28 and len(rdata) >= 16:  # AAAA
            parts = []
            for i in range(0, 16, 2):
                parts.append('{:x}'.format((rdata[i] << 8) | rdata[i+1]))
            answers.append(':'.join(parts))
        elif rtype in (2, 5, 12):  # NS, CNAME, PTR
            name = _decode_name_from_rdata(rdata)
            if name:
                answers.append(name)
        elif rtype == 15 and len(rdata) > 2:  # MX
            pref = struct.unpack('!H', rdata[:2])[0]
            name = _decode_name_from_rdata(rdata[2:])
            if name:
                answers.append(f'{pref} {name}')
        elif rtype == 16 and len(rdata) > 0:  # TXT
            txt_len = rdata[0] if len(rdata) > 0 else 0
            answers.append(rdata[1:1+txt_len].decode('utf-8', errors='ignore')[:80])

    return answers


def _decode_name_from_rdata(data):
    """从rdata中解码域名"""
    labels = []
    pos = 0
    while pos < len(data):
        length = data[pos]
        if length == 0:
            break
        if (length & 0xC0) == 0xC0:
            pos += 2
            break
        pos += 1
        if pos + length <= len(data):
            labels.append(data[pos:pos+length].decode('ascii', errors='ignore'))
            pos += length
        else:
            break
    return '.'.join(labels)


# ========== 服务探测功能 ==========
@login_required
def service_probe_index(request):
    """服务探测首页"""
    return render(request, 'dnsmgr/probe.html')


@login_required
def service_probe(request):
    """探测IP主机的端口可达性 - 支持AJAX调用"""
    if request.method != 'GET':
        return JsonResponse({'error': '仅支持GET请求'}, status=405)

    target_ip = request.GET.get('ip', '').strip()
    port_str = request.GET.get('port', '53').strip()
    timeout = float(request.GET.get('timeout', '3'))

    # 批量探测模式：多个目标（逗号分隔或换行）
    targets_raw = request.GET.get('targets', '').strip()

    if targets_raw:
        # 解析多目标
        targets = [t.strip() for t in targets_raw.replace(',', '\n').split('\n') if t.strip()]
        port = int(port_str) if port_str.isdigit() else 53
        results = [_probe_single(t, port, timeout) for t in targets]
        log_operation(request.user, '批量探测', 'dns', 'probe_batch', '', f'{len(targets)}个目标,端口{port}')
        return JsonResponse({'results': results})

    # 如果没有提供IP，返回提示
    if not target_ip:
        return JsonResponse({'error': '请提供目标IP或目标列表'}, status=400)

    try:
        port = int(port_str)
        if port < 1 or port > 65535:
            return JsonResponse({'error': f'端口无效: {port}'}, status=400)
    except ValueError:
        return JsonResponse({'error': f'端口号非法: {port_str}'}, status=400)

    result = _probe_single(target_ip, port, timeout)
    log_operation(request.user, '探测', 'dns', 'probe', '', f"{target_ip}:{port} -> {result['status']}")
    return JsonResponse(result)


def _probe_single(ip, port, timeout=3):
    """探测单个 IP:Port 的可达性"""
    start_time = time.time()
    result = {
        'ip': ip,
        'port': port,
        'status': 'unknown',
        'latency_ms': -1,
        'message': '',
    }
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        latency_ms = round((time.time() - start_time) * 1000, 1)
        sock.close()

        result['status'] = 'reachable'
        result['latency_ms'] = latency_ms
        result['message'] = f'连接成功，延迟 {latency_ms}ms'
    except socket.timeout:
        result['status'] = 'timeout'
        result['latency_ms'] = round(timeout * 1000, 1)
        result['message'] = f'连接超时 (>{timeout}s)'
    except ConnectionRefusedError:
        result['status'] = 'refused'
        result['message'] = '连接被拒绝'
    except Exception as e:
        err_msg = str(e)
        if 'Network is unreachable' in err_msg or 'No route to host' in err_msg:
            result['status'] = 'unreachable'
            result['message'] = '网络不可达'
        elif 'Name or service not known' in err_msg:
            result['status'] = 'dns_fail'
            result['message'] = 'DNS解析失败（主机名无法解析）'
        else:
            result['status'] = 'error'
            result['message'] = f'连接错误: {err_msg[:60]}'

    return result


# ========== 探测任务持久化 API ==========
@login_required
def probe_task_list(request):
    """获取当前用户的所有探测任务（返回JSON列表）"""
    tasks = ProbeTask.objects.filter(created_by=request.user).order_by('-created_at')
    data = []
    for t in tasks:
        data.append({
            'id': t.id,
            'name': t.name,
            'target': t.target,
            'port': t.port,
            'interval': t.interval,
            'status': t.status,          # running/paused/stopped
            'totalProbes': t.total_probes,
            'reachableCount': t.reachable_count,
            'timeoutCount': t.timeout_count,
            'errorCount': t.error_count,
            'lastStatus': t.last_status,
            'lastLatency': t.last_latency,
            'lastMessage': t.last_message,
            'history': t.get_history_list(),
            'createdAt': t.created_at.strftime('%Y-%m-%dT%H:%M:%S') if t.created_at else '',
        })
    return JsonResponse({'tasks': data})


@login_required
def probe_task_create(request):
    """创建新探测任务"""
    if request.method != 'POST':
        return JsonResponse({'error': '仅支持POST'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': '无效的JSON数据'}, status=400)

    name = data.get('name', '').strip()
    target = data.get('target', '').strip()

    if not name or not target:
        return JsonResponse({'error': '任务名称和目标地址不能为空'}, status=400)

    port = int(data.get('port', 22))
    interval = int(data.get('interval', 10))
    if port < 1 or port > 65535:
        return JsonResponse({'error': f'端口无效: {port}'}, status=400)
    if interval < 5:
        return JsonResponse({'error': '间隔不能小于5秒'}, status=400)

    task = ProbeTask.objects.create(
        name=name, target=target, port=port, interval=interval,
        status='running', created_by=request.user,
    )
    log_operation(request.user, '创建探测任务', 'dns', 'probe_task', '',
                  f"{name} {target}:{port} 间隔{interval}s")
    return JsonResponse({
        'id': task.id, 'name': task.name, 'target': task.target,
        'port': task.port, 'interval': task.interval, 'status': task.status,
    })


@login_required
def probe_task_update(request, pk):
    """更新任务状态（暂停/恢复/停止）或保存探测结果或编辑任务"""
    task = get_object_or_404(ProbeTask, pk=pk, created_by=request.user)

    if request.method == 'PUT':
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            return JsonResponse({'error': '无效的JSON'}, status=400)

        action = body.get('action', '')
        if action == 'pause':
            task.status = 'paused'
            task.save()
        elif action == 'resume':
            task.status = 'running'
            task.save()
        elif action == 'stop':
            task.status = 'stopped'
            task.save()
        elif action == 'edit':
            # 编辑任务属性
            name = body.get('name', '').strip()
            target = body.get('target', '').strip()
            port = body.get('port')
            interval = body.get('interval')

            if not name or not target:
                return JsonResponse({'error': '任务名称和目标地址不能为空'}, status=400)

            port = int(port) if port else task.port
            interval = int(interval) if interval else task.interval

            if port < 1 or port > 65535:
                return JsonResponse({'error': f'端口无效: {port}'}, status=400)
            if interval < 5:
                return JsonResponse({'error': '间隔不能小于5秒'}, status=400)

            task.name = name
            task.target = target
            task.port = port
            task.interval = interval
            task.save()
            log_operation(request.user, '编辑探测任务', 'dns', 'probe_task', '',
                          f"{name} {target}:{port} 间隔{interval}s")
            return JsonResponse({
                'status': 'ok',
                'task_status': task.status,
                'name': task.name,
                'target': task.target,
                'port': task.port,
                'interval': task.interval,
            })
        else:
            return JsonResponse({'error': f'未知操作: {action}'}, status=400)
        return JsonResponse({'status': 'ok', 'task_status': task.status})

    # DELETE: 删除任务（前端 stopTask 直接发到此路由）
    if request.method == 'DELETE':
        # 检查是否有DNS记录关联此探测任务
        linked_records = DNSRecord.objects.filter(probe_port=task.port)
        if task.target:
            linked_records = linked_records.filter(
                models.Q(value__iexact=task.target) | models.Q(linked_ip=task.target)
            )
        if linked_records.exists():
            rec_names = list(linked_records.values_list('name', flat=True)[:5])
            hint = ', '.join(rec_names)
            if linked_records.count() > 5:
                hint += f' 等共{linked_records.count()}条'
            return JsonResponse({
                'error': f'无法删除：该探测任务已被 {linked_records.count()} 条DNS记录关联 ({hint})。请先解除关联后再删除。',
                'code': 'HAS_LINKED_RECORDS',
                'linked_count': linked_records.count(),
                'linked_records': hint,
            }, status=409)

        name = task.name
        task.delete()
        log_operation(request.user, '删除探测任务', 'dns', 'probe_task', '', name)
        return JsonResponse({'status': 'ok'})

    # POST: 保存单次探测结果（前端每次探测后回调）
    if request.method == 'POST':
        try:
            result_data = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            return JsonResponse({'error': '无效JSON'}, status=400)

        # 更新统计
        task.total_probes += 1
        status = result_data.get('status', '')
        if status == 'reachable':
            task.reachable_count += 1
        elif status in ('timeout', 'unreachable'):
            task.timeout_count += 1
        else:
            task.error_count += 1

        # 更新最近结果
        task.last_status = status
        task.last_latency = result_data.get('latency_ms')
        task.last_message = result_data.get('message', '')[:200]

        # 追加历史
        hlist = task.get_history_list()
        hlist.append({
            'status': status,
            'latency': result_data.get('latency_ms'),
            'message': result_data.get('message', ''),
        })
        task.set_history(hlist)
        task.save()
        return JsonResponse({'status': 'ok'})

    return JsonResponse({'error': '仅支持PUT/POST/DELETE'}, status=405)


@login_required
def probe_task_delete(request, pk):
    """删除探测任务（备用路由）"""
    if request.method not in ('DELETE', 'POST'):
        return JsonResponse({'error': '仅支持DELETE/POST'}, status=405)
    task = get_object_or_404(ProbeTask, pk=pk, created_by=request.user)

    # 检查是否有DNS记录关联此探测任务
    linked_records = DNSRecord.objects.filter(probe_port=task.port)
    if task.target:
        linked_records = linked_records.filter(
            models.Q(value__iexact=task.target) | models.Q(linked_ip=task.target)
        )
    if linked_records.exists():
        rec_names = list(linked_records.values_list('name', flat=True)[:5])
        hint = ', '.join(rec_names)
        if linked_records.count() > 5:
            hint += f' 等共{linked_records.count()}条'
        return JsonResponse({
            'error': f'无法删除：该探测任务已被 {linked_records.count()} 条DNS记录关联 ({hint})。请先解除关联后再删除。',
            'code': 'HAS_LINKED_RECORDS',
            'linked_count': linked_records.count(),
            'linked_records': hint,
        }, status=409)

    name = task.name
    task.delete()
    log_operation(request.user, '删除探测任务', 'dns', 'probe_task', '', name)
    return JsonResponse({'status': 'ok'})
