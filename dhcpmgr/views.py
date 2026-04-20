"""
DHCP管理模块 - 视图函数
提供地址池CRUD、排除地址管理、租约管理、服务启停等功能
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from .models import DHCPPool, DHCPExclusion, DHCPLease, DHCPLog
from .forms import DHCPPoolForm, DHCPExclusionForm, DHCPLeaseForm, DHCPLeaseSearchForm
from common.logger import log_operation
from django.utils import timezone
import time


# ========== DHCP地址池管理 ==========
@method_decorator([login_required], name='dispatch')
class PoolListView(ListView):
    """地址池列表视图 - 支持按名称/CIDR搜索，预加载子网信息"""
    model = DHCPPool
    template_name = 'dhcpmgr/pool_list.html'
    context_object_name = 'pools'
    
    def get_queryset(self):
        """预加载子网关联数据，支持按地址池名称和子网CIDR模糊搜索"""
        queryset = super().get_queryset().select_related('subnet')
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(name__icontains=search) | \
                       queryset.filter(subnet__cidr__icontains=search)
        return queryset


@method_decorator([login_required], name='dispatch')
class PoolDetailView(DetailView):
    """地址池详情视图 - 展示排除地址和租约列表"""
    model = DHCPPool
    template_name = 'dhcpmgr/pool_detail.html'
    context_object_name = 'pool'
    
    def get_context_data(self, **kwargs):
        """加载排除地址列表和最近50条租约"""
        context = super().get_context_data(**kwargs)
        context['exclusions'] = self.object.exclusions.all()
        context['leases'] = self.object.leases.all()[:50]  # 限制数量，避免大量租约拖慢页面
        return context


@method_decorator([login_required], name='dispatch')
class PoolCreateView(CreateView):
    """创建地址池视图"""
    model = DHCPPool
    form_class = DHCPPoolForm
    template_name = 'dhcpmgr/pool_form.html'
    success_url = reverse_lazy('dhcpmgr:pool_list')
    
    def form_valid(self, form):
        """创建成功后记录操作日志"""
        messages.success(self.request, f'DHCP地址池 {form.instance.name} 创建成功')
        log_operation(self.request.user, '新增', 'dhcp', 'pool', '', str(form.instance))
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class PoolUpdateView(UpdateView):
    """编辑地址池视图 - 修改地址范围、网关、DNS、租约时间等"""
    model = DHCPPool
    form_class = DHCPPoolForm
    template_name = 'dhcpmgr/pool_form.html'
    success_url = reverse_lazy('dhcpmgr:pool_list')

    def form_valid(self, form):
        messages.success(self.request, f'地址池 {form.instance.name} 更新成功')
        log_operation(self.request.user, '编辑', 'dhcp', 'pool', '', str(form.instance))
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class PoolDeleteView(DeleteView):
    """删除地址池视图 - 删除前需用户确认"""
    model = DHCPPool
    template_name = 'dhcpmgr/confirm_delete.html'
    success_url = reverse_lazy('dhcpmgr:pool_list')


@login_required
def toggle_pool_status(request, pk):
    """启用/禁用地址池 - 切换地址池的启用状态"""
    pool = get_object_or_404(DHCPPool, pk=pk)
    old_status = pool.get_status_display()
    
    if pool.status == 'enabled':
        pool.status = 'disabled'
        messages.success(request, f'地址池 {pool.name} 已禁用')
    else:
        pool.status = 'enabled'
        messages.success(request, f'地址池 {pool.name} 已启用')
    pool.save()
    
    log_operation(request.user, '修改状态', 'dhcp', 'pool', old_status,
                 f"{pool.name}->{pool.get_status_display()}")
    return redirect('dhcpmgr:pool_list')


# ========== 排除地址管理 ==========
@method_decorator([login_required], name='dispatch')
class ExclusionCreateView(CreateView):
    """创建排除地址视图 - 排除地址范围内的IP不参与DHCP分配"""
    model = DHCPExclusion
    form_class = DHCPExclusionForm
    template_name = 'dhcpmgr/exclusion_form.html'
    
    def get_initial(self):
        initial = super().get_initial()
        pool_id = self.request.GET.get('pool')
        if pool_id:
            initial['pool'] = pool_id
        return initial
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, '排除地址段添加成功')
        log_operation(self.request.user, '新增', 'dhcp', 'exclusion', '', str(self.object))
        # 跳转到地址池详情页
        return redirect('dhcpmgr:pool_detail', pk=self.object.pool.pk)


@method_decorator([login_required], name='dispatch')
class ExclusionUpdateView(UpdateView):
    """编辑排除地址视图"""
    model = DHCPExclusion
    form_class = DHCPExclusionForm
    template_name = 'dhcpmgr/exclusion_form.html'
    
    def get_success_url(self):
        return reverse_lazy('dhcpmgr:pool_detail', kwargs={'pk': self.object.pool.pk})


@method_decorator([login_required], name='dispatch')
class ExclusionDeleteView(DeleteView):
    """删除排除地址视图 - 删除后跳回地址池详情页"""
    model = DHCPExclusion
    template_name = 'dhcpmgr/confirm_delete.html'

    def get_success_url(self):
        if self.object and self.object.pool_id:
            return reverse_lazy('dhcpmgr:pool_detail', kwargs={'pk': self.object.pool_id})
        return reverse_lazy('dhcpmgr:pool_list')

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        log_operation(request.user, '删除', 'dhcp', 'exclusion', '', str(obj))
        response = super().delete(request, *args, **kwargs)
        messages.success(request, '排除地址段已删除')
        return response


# ========== 租约管理 ==========
@method_decorator([login_required], name='dispatch')
class LeaseListView(ListView):
    """租约列表视图 - 支持按IP/MAC/主机名搜索和按状态/地址池筛选"""
    model = DHCPLease
    template_name = 'dhcpmgr/lease_list.html'
    context_object_name = 'leases'
    paginate_by = 25
    
    def get_queryset(self):
        """预加载地址池和子网关联数据，支持多条件筛选"""
        queryset = super().get_queryset().select_related('pool', 'pool__subnet')
        
        form = DHCPLeaseSearchForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            status = form.cleaned_data.get('status')
            pool = form.cleaned_data.get('pool')
            
            if search:
                queryset = queryset.filter(
                    ip_address__icontains=search
                ) | queryset.filter(
                    mac_address__icontains=search
                ) | queryset.filter(
                    hostname__icontains=search
                )
            if status:
                queryset = queryset.filter(status=status)
            else:
                # 默认不显示已释放的租约
                queryset = queryset.exclude(status='released')
            if pool:
                queryset = queryset.filter(pool=pool)
        
        return queryset.order_by('-end_time')


@login_required
def lease_create(request):
    """手动添加租约 - 用于静态绑定等场景"""
    if request.method == 'POST':
        form = DHCPLeaseForm(request.POST)
        if form.is_valid():
            # 检查该IP是否已有其他MAC的活跃租约
            ip = form.cleaned_data.get('ip_address')
            mac = form.cleaned_data.get('mac_address', '').upper()
            existing = DHCPLease.objects.filter(
                ip_address=ip,
                status='active'
            ).exclude(mac_address=mac).first()
            if existing:
                messages.error(
                    request,
                    f'IP {ip} 已被 MAC={existing.mac_address} 占用，请先释放该租约后再创建'
                )
                return render(request, 'dhcpmgr/lease_form.html', {'form': form})

            # 检查该MAC是否已有其他IP的活跃租约（同一MAC仅保留一条）
            old_leases = DHCPLease.objects.filter(
                mac_address=mac,
                status='active',
            ).exclude(ip_address=ip)
            if old_leases.exists():
                ips = list(old_leases.values_list('ip_address', flat=True))
                messages.warning(
                    request,
                    f'MAC {mac} 已有活跃租约 ({", ".join(ips)})，已自动释放旧租约'
                )
                old_leases.update(status='released')

            lease = form.save()
            messages.success(request, f'租约 {lease.ip_address} 创建成功')
            log_operation(request.user, '新增', 'dhcp', 'lease', '', str(lease))
            return redirect('dhcpmgr:lease_list')
    else:
        form = DHCPLeaseForm(initial={'status': 'active'})
    
    return render(request, 'dhcpmgr/lease_form.html', {'form': form})


@login_required
def lease_release(request, pk):
    """释放租约 - 将租约状态置为released"""
    lease = get_object_or_404(DHCPLease, pk=pk)
    
    if request.method == 'POST':
        old_info = str(lease)
        lease.release()
        messages.success(request, f'租约 {lease.ip_address} 已释放')
        log_operation(request.user, '释放', 'dhcp', 'lease', old_info, f'{lease.ip_address}->已释放')
        return redirect('dhcpmgr:lease_list')
    
    return render(request, 'dhcpmgr/lease_confirm.html', {'lease': lease})


@login_required
def check_expired_leases(request):
    """检查过期租约 - 批量将超时未续约的active租约标记为expired"""
    now = timezone.now()
    expired_leases = DHCPLease.objects.filter(
        status='active',
        end_time__lt=now
    )
    
    count = expired_leases.count()
    expired_leases.update(status='expired')
    
    messages.info(request, f'已更新 {count} 条过期租约状态')
    return redirect('dhcpmgr:lease_list')


@login_required
def release_all_leases(request):
    """一键释放所有活跃租约 - 将所有active状态租约置为released"""
    if request.method != 'POST':
        return redirect('dhcpmgr:lease_list')

    count = DHCPLease.objects.filter(status='active').update(status='released')
    
    # 同时清空DHCP服务内存中的分配记录
    try:
        from .dhcp_server import get_dhcp_server
        server = get_dhcp_server()
        with server._lock:
            server._allocated_ips.clear()
    except Exception:
        pass

    messages.success(request, f'已释放全部 {count} 条活跃租约')
    log_operation(request.user, '批量释放', 'dhcp', 'lease', '', f'释放{count}条租约')
    return redirect('dhcpmgr:lease_list')


# ========== DHCP服务管理 ==========
@login_required
def dhcp_service_page(request):
    """DHCP服务管理页面 - 展示服务状态和地址池列表"""
    from .dhcp_server import get_dhcp_server
    server = get_dhcp_server()
    
    context = {
        'status': server.get_status(),
        'pools': DHCPPool.objects.all().select_related('subnet'),
    }
    return render(request, 'dhcpmgr/service.html', context)


@login_required
def dhcp_service_start(request):
    """启动DHCP服务"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持POST请求'})

    from .dhcp_server import get_dhcp_server
    server = get_dhcp_server()
    
    try:
        success, message = server.start()
        
        log_operation(
            request.user, '启动服务', 'dhcp', 'service',
            '', message
        )
        
        # 判断是AJAX还是普通表单提交
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': success,
                'message': message,
                'status': server.get_status(),
            })  # AJAX请求直接返回JSON
        
        # 普通表单提交：带消息重定向回页面
        from django.contrib import messages
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        return redirect('dhcpmgr:service')
            
    except Exception as e:
        error_msg = f'启动异常: {str(e)}'
        
        # 异常处理：根据请求类型返回对应格式
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': error_msg,
                'status': server.get_status(),
            })
        
        from django.contrib import messages
        messages.error(request, error_msg)
        return redirect('dhcpmgr:service')


@login_required
def dhcp_service_stop(request):
    """停止DHCP服务"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持POST请求'})

    from .dhcp_server import get_dhcp_server
    server = get_dhcp_server()
    
    try:
        success, message = server.stop()
        
        log_operation(
            request.user, '停止服务', 'dhcp', 'service',
            '', message
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': success,
                'message': message,
                'status': server.get_status(),
            })
        
        from django.contrib import messages
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        return redirect('dhcpmgr:service')
            
    except Exception as e:
        error_msg = f'停止异常: {str(e)}'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': error_msg,
                'status': server.get_status(),
            })
        
        from django.contrib import messages
        messages.error(request, error_msg)
        return redirect('dhcpmgr:service')


@login_required
def dhcp_service_status(request):
    """获取DHCP服务状态（AJAX接口） - 返回运行状态、运行时间、地址池等"""
    from .dhcp_server import get_dhcp_server
    server = get_dhcp_server()
    
    return JsonResponse(server.get_status())


# ========== DHCP地址获取日志 ==========
@method_decorator([login_required], name='dispatch')
class DHCPLogListView(ListView):
    """DHCP地址获取日志 - 显示客户端DISCOVER/OFFER/REQUEST/ACK/NAK/RELEASE交互记录"""
    model = DHCPLog
    template_name = 'dhcpmgr/log_list.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        """支持按MAC/IP/消息类型筛选"""
        queryset = super().get_queryset()
        
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                mac_address__icontains=search
            ) | queryset.filter(
                ip_address__icontains=search
            )

        msg_type = self.request.GET.get('msg_type', '')
        if msg_type:
            queryset = queryset.filter(msg_type=msg_type)

        status = self.request.GET.get('status', '')
        if status:
            queryset = queryset.filter(status=status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['msg_type_choices'] = DHCPLog.MSG_TYPE_CHOICES
        context['status_choices'] = DHCPLog.STATUS_CHOICES
        context['search'] = self.request.GET.get('search', '')
        context['current_msg_type'] = self.request.GET.get('msg_type', '')
        context['current_status'] = self.request.GET.get('status', '')
        # 统计信息
        from django.db.models import Count
        context['total_count'] = DHCPLog.objects.count()
        context['today_count'] = DHCPLog.objects.filter(
            created_at__date__gte=timezone.now().date()
        ).count()
        return context


@login_required
def dhcp_log_clear(request):
    """清空DHCP日志"""
    if request.method == 'POST':
        count = DHCPLog.objects.all().delete()[0]
        messages.success(request, f'已清空 {count} 条DHCP日志')
        log_operation(request.user, '清空日志', 'dhcp', 'log', '', f'删除{count}条')
    return redirect('dhcpmgr:log_list')
