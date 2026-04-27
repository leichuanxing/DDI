"""
设备管理模块 - 视图函数
提供设备CRUD、设备与IP关联等功能
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy
from django.contrib import messages
from .models import Device
from .forms import DeviceForm, DeviceSearchForm
from common.logger import log_operation


@method_decorator([login_required], name='dispatch')
class DeviceListView(ListView):
    """设备列表视图 - 支持按主机名/设备名/MAC搜索和按类型/区域筛选"""
    model = Device
    template_name = 'devices/device_list.html'
    context_object_name = 'devices'
    paginate_by = 20
    
    def get_queryset(self):
        """支持多条件搜索筛选：关键字模糊搜索(主机名/设备名/MAC)、类型筛选、区域筛选"""
        queryset = super().get_queryset().select_related('region', 'ip_address')
        form = DeviceSearchForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            device_type = form.cleaned_data.get('device_type')
            region = form.cleaned_data.get('region')
            
            if search:
                queryset = queryset.filter(
                    hostname__icontains=search
                ) | queryset.filter(
                    device_name__icontains=search
                ) | queryset.filter(
                    mac_address__icontains=search
                )
            if device_type:
                queryset = queryset.filter(device_type=device_type)
            if region:
                queryset = queryset.filter(region=region)
        
        return queryset.order_by('hostname')


@method_decorator([login_required], name='dispatch')
class DeviceDetailView(DetailView):
    """设备详情视图 - 展示关联DNS记录和网络接口"""
    model = Device
    template_name = 'devices/device_detail.html'
    context_object_name = 'device'
    
    def get_context_data(self, **kwargs):
        """加载网络接口列表"""
        context = super().get_context_data(**kwargs)
        device = self.object
        # 查询该设备的所有网络接口（支持多网卡场景）
        context['interfaces'] = device.interfaces.all()
        
        return context


@method_decorator([login_required], name='dispatch')
class DeviceCreateView(CreateView):
    """创建设备视图"""
    model = Device
    form_class = DeviceForm
    template_name = 'devices/device_form.html'
    success_url = reverse_lazy('devices:device_list')
    
    def form_valid(self, form):
        """表单验证通过后，记录创建人并写操作日志"""
        form.instance.created_by = self.request.user  # 自动填充创建人为当前登录用户
        messages.success(self.request, f'设备 {form.instance.hostname} 创建成功')
        log_operation(self.request.user, '新增', 'devices', 'device', '', form.instance.hostname)
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class DeviceUpdateView(UpdateView):
    """编辑设备视图 - 修改设备属性信息"""
    model = Device
    form_class = DeviceForm
    template_name = 'devices/device_form.html'
    success_url = reverse_lazy('devices:device_list')


@method_decorator([login_required], name='dispatch')
class DeviceDeleteView(DeleteView):
    """删除设备视图 - 删除前需用户确认"""
    model = Device
    template_name = 'devices/confirm_delete.html'
    success_url = reverse_lazy('devices:device_list')


@login_required
def link_device_to_ip(request, device_pk, ip_pk):
    """将设备关联到IP地址 - 建立设备与IP的一对一映射"""
    from ipam.models import IPAddress
    
    device = get_object_or_404(Device, pk=device_pk)
    ip_obj = get_object_or_404(IPAddress, pk=ip_pk)
    
    # 检查IP是否已分配给其他设备（避免重复关联）
    existing_device = Device.objects.filter(ip_address=ip_obj).exclude(pk=device_pk).first()
    if existing_device and request.method == 'POST':
        messages.warning(request, f'该IP已关联到设备 {existing_device.hostname}')
        return redirect('devices:device_detail', pk=device.pk)
    
    if request.method == 'POST':
        old_ip = device.ip_address
        device.ip_address = ip_obj
        device.save()
        
        log_operation(request.user, '关联', 'devices', 'device_ip',
                     str(old_ip), f"{device.hostname}->{ip_obj.ip_address}")
        
        messages.success(request, f'设备 {device.hostname} 已关联到 IP {ip_obj.ip_address}')
        return redirect('devices:device_detail', pk=device.pk)
    
    return render(request, 'devices/link_ip.html', {'device': device, 'ip': ip_obj})
