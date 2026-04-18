from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from .models import DHCPPool, DHCPExclusion, DHCPLease
from .forms import DHCPPoolForm, DHCPExclusionForm, DHCPLeaseForm, DHCPLeaseSearchForm
from common.logger import log_operation
from django.utils import timezone
import time


# ========== DHCP地址池管理 ==========
@method_decorator([login_required], name='dispatch')
class PoolListView(ListView):
    model = DHCPPool
    template_name = 'dhcpmgr/pool_list.html'
    context_object_name = 'pools'
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('subnet')
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(name__icontains=search) | \
                       queryset.filter(subnet__cidr__icontains=search)
        return queryset


@method_decorator([login_required], name='dispatch')
class PoolDetailView(DetailView):
    model = DHCPPool
    template_name = 'dhcpmgr/pool_detail.html'
    context_object_name = 'pool'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exclusions'] = self.object.exclusions.all()
        context['leases'] = self.object.leases.all()[:50]
        return context


@method_decorator([login_required], name='dispatch')
class PoolCreateView(CreateView):
    model = DHCPPool
    form_class = DHCPPoolForm
    template_name = 'dhcpmgr/pool_form.html'
    success_url = reverse_lazy('dhcpmgr:pool_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'DHCP地址池 {form.instance.name} 创建成功')
        log_operation(self.request.user, '新增', 'dhcp', 'pool', '', str(form.instance))
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class PoolUpdateView(UpdateView):
    model = DHCPPool
    form_class = DHCPPoolForm
    template_name = 'dhcpmgr/pool_form.html'
    success_url = reverse_lazy('dhcpmgr:pool_list')


@method_decorator([login_required], name='dispatch')
class PoolDeleteView(DeleteView):
    model = DHCPPool
    template_name = 'dhcpmgr/confirm_delete.html'
    success_url = reverse_lazy('dhcpmgr:pool_list')


@login_required
def toggle_pool_status(request, pk):
    """启用/禁用地址池"""
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
        response = super().form_valid(form)
        messages.success(self.request, '排除地址段添加成功')
        log_operation(self.request.user, '新增', 'dhcp', 'exclusion', '', str(self.object))
        # 跳转到地址池详情页
        return redirect('dhcpmgr:pool_detail', pk=self.object.pool.pk)


@method_decorator([login_required], name='dispatch')
class ExclusionUpdateView(UpdateView):
    model = DHCPExclusion
    form_class = DHCPExclusionForm
    template_name = 'dhcpmgr/exclusion_form.html'
    
    def get_success_url(self):
        return reverse_lazy('dhcpmgr:pool_detail', kwargs={'pk': self.object.pool.pk})


@method_decorator([login_required], name='dispatch')
class ExclusionDeleteView(DeleteView):
    model = DHCPExclusion
    template_name = 'dhcpmgr/confirm_delete.html'
    
    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        pool_pk = obj.pool.pk
        log_operation(request.user, '删除', 'dhcp', 'exclusion', '', str(obj))
        response = super().delete(request, *args, **kwargs)
        messages.success(request, '排除地址段已删除')
        return redirect('dhcpmgr:pool_detail', pk=pool_pk)


# ========== 租约管理 ==========
@method_decorator([login_required], name='dispatch')
class LeaseListView(ListView):
    model = DHCPLease
    template_name = 'dhcpmgr/lease_list.html'
    context_object_name = 'leases'
    paginate_by = 25
    
    def get_queryset(self):
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
            if pool:
                queryset = queryset.filter(pool=pool)
        
        return queryset.order_by('-end_time')


@login_required
def lease_create(request):
    """手动添加租约"""
    if request.method == 'POST':
        form = DHCPLeaseForm(request.POST)
        if form.is_valid():
            lease = form.save()
            messages.success(request, f'租约 {lease.ip_address} 创建成功')
            log_operation(request.user, '新增', 'dhcp', 'lease', '', str(lease))
            return redirect('dhcpmgr:lease_list')
    else:
        form = DHCPLeaseForm(initial={'status': 'active'})
    
    return render(request, 'dhcpmgr/lease_form.html', {'form': form})


@login_required
def lease_release(request, pk):
    """释放租约"""
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
    """检查过期租约"""
    now = timezone.now()
    expired_leases = DHCPLease.objects.filter(
        status='active',
        end_time__lt=now
    )
    
    count = expired_leases.count()
    expired_leases.update(status='expired')
    
    messages.info(request, f'已更新 {count} 条过期租约状态')
    return redirect('dhcpmgr:lease_list')


# ========== DHCP服务管理 ==========
@login_required
def dhcp_service_page(request):
    """DHCP服务管理页面"""
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
            })
        
        # 普通表单提交：带消息重定向回页面
        from django.contrib import messages
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        return redirect('dhcpmgr:service')
            
    except Exception as e:
        error_msg = f'启动异常: {str(e)}'
        
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
    """获取DHCP服务状态 (AJAX)"""
    from .dhcp_server import get_dhcp_server
    server = get_dhcp_server()
    
    return JsonResponse(server.get_status())
