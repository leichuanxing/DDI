from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from .models import Region, VLAN, Subnet, IPAddress
from .forms import RegionForm, VLANForm, SubnetForm, IPAddressAllocateForm, IPBatchAllocateForm
from common.logger import log_operation
import ipaddress


# ========== 区域管理 ==========
@method_decorator([login_required], name='dispatch')
class RegionListView(ListView):
    model = Region
    template_name = 'ipam/region_list.html'
    context_object_name = 'regions'


@method_decorator([login_required], name='dispatch')
class RegionCreateView(CreateView):
    model = Region
    form_class = RegionForm
    template_name = 'ipam/region_form.html'
    success_url = reverse_lazy('ipam:region_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'区域 {form.instance.name} 创建成功')
        log_operation(self.request.user, '新增', 'ipam', 'region', '', form.instance.name)
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class RegionUpdateView(UpdateView):
    model = Region
    form_class = RegionForm
    template_name = 'ipam/region_form.html'
    success_url = reverse_lazy('ipam:region_list')


@method_decorator([login_required], name='dispatch')
class RegionDeleteView(DeleteView):
    model = Region
    template_name = 'ipam/confirm_delete.html'
    success_url = reverse_lazy('ipam:region_list')


# ========== VLAN管理 ==========
@method_decorator([login_required], name='dispatch')
class VLANListView(ListView):
    model = VLAN
    template_name = 'ipam/vlan_list.html'
    context_object_name = 'vlans'
    
    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(name__icontains=search) | \
                       queryset.filter(vlan_id__icontains=search)
        return queryset.select_related('region')


@method_decorator([login_required], name='dispatch')
class VLANCreateView(CreateView):
    model = VLAN
    form_class = VLANForm
    template_name = 'ipam/vlan_form.html'
    success_url = reverse_lazy('ipam:vlan_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'VLAN {form.instance.vlan_id} 创建成功')
        log_operation(self.request.user, '新增', 'ipam', 'vlan', '', f"VLAN{form.instance.vlan_id}")
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class VLANUpdateView(UpdateView):
    model = VLAN
    form_class = VLANForm
    template_name = 'ipam/vlan_form.html'
    success_url = reverse_lazy('ipam:vlan_list')


@method_decorator([login_required], name='dispatch')
class VLANDeleteView(DeleteView):
    model = VLAN
    template_name = 'ipam/confirm_delete.html'
    success_url = reverse_lazy('ipam:vlan_list')


# ========== 子网管理 ==========
@method_decorator([login_required], name='dispatch')
class SubnetListView(ListView):
    model = Subnet
    template_name = 'ipam/subnet_list.html'
    context_object_name = 'subnets'
    
    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('search', '')
        region = self.request.GET.get('region', '')
        if search:
            queryset = queryset.filter(name__icontains=search) | \
                       queryset.filter(cidr__icontains=search)
        if region:
            queryset = queryset.filter(region__id=region)
        return queryset.select_related('region', 'vlan').prefetch_related('ip_addresses')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['region'] = self.request.GET.get('region', '')
        context['regions'] = Region.objects.all()
        return context


@login_required
def subnet_detail(request, pk):
    """子网详情页，显示IP地址池"""
    subnet = get_object_or_404(Subnet, pk=pk)
    
    # 获取该子网下的所有IP
    ips = subnet.ip_addresses.all()
    
    # 状态筛选
    status_filter = request.GET.get('status', '')
    if status_filter:
        ips = ips.filter(status=status_filter)
    
    # 搜索
    search = request.GET.get('search', '')
    if search:
        ips = ips.filter(ip_address__icontains=search) | \
               ips.filter(hostname__icontains=search) | \
               ips.filter(device_name__icontains=search)
    
    # 按IP地址数值排序（确保 1 排在 10 前面）
    import ipaddress
    ips_list = list(ips)
    ips_list.sort(key=lambda x: int(ipaddress.ip_address(x.ip_address)))
    ips = ips_list
    
    # 统计信息
    stats = {
        'total': subnet.total_ips,
        'allocated': subnet.allocated_ips,
        'available': subnet.available_ips,
        'reserved': subnet.ip_addresses.filter(status='reserved').count(),
        'conflict': subnet.ip_addresses.filter(status='conflict').count(),
    }
    
    return render(request, 'ipam/subnet_detail.html', {
        'subnet': subnet,
        'ips': ips,
        'stats': stats,
        'status_filter': status_filter,
        'search': search,
    })


@method_decorator([login_required], name='dispatch')
class SubnetCreateView(CreateView):
    model = Subnet
    form_class = SubnetForm
    template_name = 'ipam/subnet_form.html'
    success_url = reverse_lazy('ipam:subnet_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'子网 {form.instance.cidr} 创建成功')
        log_operation(self.request.user, '新增', 'ipam', 'subnet', '', form.instance.cidr)
        # 自动生成IP地址清单
        self.generate_ip_pool(form.instance)
        return response
    
    def generate_ip_pool(self, subnet):
        """自动生成IP地址清单"""
        from common.ip_utils import get_ip_list_from_subnet
        ip_list = get_ip_list_from_subnet(subnet.cidr)
        ip_objects = []
        for ip in ip_list:
            # 检查是否为网关地址
            status = 'available'
            if ip == subnet.gateway:
                status = 'reserved'
            
            ip_objects.append(IPAddress(
                ip_address=ip,
                subnet=subnet,
                status=status,
                created_by=self.request.user if self.request.user.is_authenticated else None
            ))
        IPAddress.objects.bulk_create(ip_objects)


@method_decorator([login_required], name='dispatch')
class SubnetUpdateView(UpdateView):
    model = Subnet
    form_class = SubnetForm
    template_name = 'ipam/subnet_form.html'
    success_url = reverse_lazy('ipam:subnet_list')


@method_decorator([login_required], name='dispatch')
class SubnetDeleteView(DeleteView):
    model = Subnet
    template_name = 'ipam/confirm_delete.html'
    success_url = reverse_lazy('ipam:subnet_list')


# ========== IP地址管理 ==========
@method_decorator([login_required], name='dispatch')
class IPAddressListView(ListView):
    model = IPAddress
    template_name = 'ipam/ip_list.html'
    context_object_name = 'ips'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('subnet')
        
        search = self.request.GET.get('search', '')
        status = self.request.GET.get('status', '')
        subnet = self.request.GET.get('subnet', '')
        
        if search:
            queryset = queryset.filter(
                ip_address__icontains=search
            ) | queryset.filter(
                hostname__icontains=search
            ) | queryset.filter(
                mac_address__icontains=search
            ) | queryset.filter(
                device_name__icontains=search
            )
        
        if status:
            queryset = queryset.filter(status=status)
        
        if subnet:
            queryset = queryset.filter(subnet__id=subnet)
        
        return queryset.order_by('ip_address')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['status'] = self.request.GET.get('status', '')
        context['subnet'] = self.request.GET.get('subnet', '')
        context['subnets'] = Subnet.objects.all()
        context['status_choices'] = IPAddress.STATUS_CHOICES
        return context


@login_required
def ip_allocate(request, pk):
    """分配单个IP"""
    ip_obj = get_object_or_404(IPAddress, pk=pk)
    
    if ip_obj.status == 'allocated':
        messages.error(request, f'IP {ip_obj.ip_address} 已被分配，无法重复分配')
        return redirect('ipam:ip_list')
    
    if request.method == 'POST':
        form = IPAddressAllocateForm(request.POST, instance=ip_obj)
        if form.is_valid():
            ip_obj = form.save(commit=False)
            ip_obj.status = 'allocated'
            ip_obj.created_by = request.user
            ip_obj.save()
            messages.success(request, f'IP {ip_obj.ip_address} 分配成功')
            log_operation(request.user, '分配', 'ipam', 'ip', '', f"{ip_obj.ip_address}->{ip_obj.device_name or ip_obj.hostname}")
            return redirect('ipam:ip_list')
    else:
        form = IPAddressAllocateForm(instance=ip_obj)
    
    return render(request, 'ipam/ip_allocate.html', {'form': form, 'ip': ip_obj})


@login_required
def ip_release(request, pk):
    """释放IP"""
    ip_obj = get_object_or_404(IPAddress, pk=pk)
    
    if request.method == 'POST':
        old_info = f"IP:{ip_obj.ip_address}, 主机:{ip_obj.hostname}, 设备:{ip_obj.device_name}"
        ip_obj.release()
        messages.success(request, f'IP {ip_obj.ip_address} 已释放')
        log_operation(request.user, '释放', 'ipam', 'ip', old_info, f'{ip_obj.ip_address}->空闲')
        return redirect('ipam:ip_list')
    
    return render(request, 'ipam/ip_confirm_release.html', {'ip': ip_obj})


@login_required
def ip_set_status(request, pk, status):
    """设置IP状态（保留、冲突、禁用）"""
    ip_obj = get_object_or_404(IPAddress, pk=pk)
    valid_statuses = ['reserved', 'conflict', 'disabled']
    
    if status not in valid_statuses:
        messages.error(request, '无效的状态操作')
        return redirect('ipam:ip_list')
    
    if request.method == 'POST':
        old_status = ip_obj.get_status_display()
        ip_obj.status = status
        ip_obj.save()
        messages.success(request, f'IP {ip_obj.ip_address} 已标记为 {ip_obj.get_status_display()}')
        log_operation(request.user, '标记', 'ipam', 'ip', old_status, 
                     f"{ip_obj.ip_address}->{ip_obj.get_status_display()}")
        return redirect('ipam:ip_list')
    
    return render(request, 'ipam/ip_confirm_action.html', {'ip': ip_obj, 'action': status})


@login_required
def batch_allocate(request, subnet_pk):
    """批量分配IP"""
    subnet = get_object_or_404(Subnet, pk=subnet_pk)
    
    if request.method == 'POST':
        form = IPBatchAllocateForm(request.POST)
        if form.is_valid():
            start_ip = form.cleaned_data['start_ip']
            end_ip = form.cleaned_data['end_ip']
            device_type = form.cleaned_data.get('device_type', '')
            department = form.cleaned_data.get('department', '')
            notes = form.cleaned_data.get('notes', '')
            
            # 获取IP范围
            start = int(ipaddress.ip_address(start_ip))
            end = int(ipaddress.ip_address(end_ip))
            
            if start > end:
                messages.error(request, '起始IP不能大于结束IP')
                return redirect('ipam:batch_allocate', subnet_pk=subnet_pk)
            
            allocated_count = 0
            for i in range(start, end + 1):
                ip_str = str(ipaddress.ip_address(i))
                try:
                    ip_obj = IPAddress.objects.get(ip_address=ip_str, subnet=subnet)
                    if ip_obj.status == 'available':
                        ip_obj.status = 'allocated'
                        ip_obj.device_type = device_type
                        ip_obj.department = department
                        ip_obj.notes = notes
                        ip_obj.created_by = request.user
                        ip_obj.save()
                        allocated_count += 1
                except IPAddress.DoesNotExist:
                    continue
            
            messages.success(request, f'成功批量分配 {allocated_count} 个IP')
            log_operation(request.user, '批量分配', 'ipam', 'ip', '', 
                         f"子网:{subnet.cidr}, 数量:{allocated_count}")
            return redirect('ipam:subnet_detail', pk=subnet.pk)
    else:
        form = IPBatchAllocateForm()
    
    return render(request, 'ipam/batch_allocate.html', {
        'form': form, 
        'subnet': subnet,
        'available_ips': subnet.ip_addresses.filter(status='available').order_by('ip_address')[:50]
    })
