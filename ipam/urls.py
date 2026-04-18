from django.urls import path
from .views import (
    RegionListView, RegionCreateView, RegionUpdateView, RegionDeleteView,
    VLANListView, VLANCreateView, VLANUpdateView, VLANDeleteView,
    SubnetListView, subnet_detail, SubnetCreateView, SubnetUpdateView, SubnetDeleteView,
    IPAddressListView, ip_allocate, ip_release, ip_set_status, batch_allocate
)
from .scan_views import (
    scan_index, create_scan_task, scan_task_detail, execute_scan,
    get_scan_progress, cancel_scan, quick_ping, quick_port_scan,
    probe_history, discovery_rules, delete_scan_task, export_scan_results,
    live_topology, quick_allocate_ip
)

app_name = 'ipam'

urlpatterns = [
    # 区域管理
    path('regions/', RegionListView.as_view(), name='region_list'),
    path('regions/create/', RegionCreateView.as_view(), name='region_create'),
    path('regions/<int:pk>/edit/', RegionUpdateView.as_view(), name='region_edit'),
    path('regions/<int:pk>/delete/', RegionDeleteView.as_view(), name='region_delete'),
    
    # VLAN管理
    path('vlans/', VLANListView.as_view(), name='vlan_list'),
    path('vlans/create/', VLANCreateView.as_view(), name='vlan_create'),
    path('vlans/<int:pk>/edit/', VLANUpdateView.as_view(), name='vlan_edit'),
    path('vlans/<int:pk>/delete/', VLANDeleteView.as_view(), name='vlan_delete'),
    
    # 子网管理
    path('subnets/', SubnetListView.as_view(), name='subnet_list'),
    path('subnets/create/', SubnetCreateView.as_view(), name='subnet_create'),
    path('subnets/<int:pk>/', subnet_detail, name='subnet_detail'),
    path('subnets/<int:pk>/edit/', SubnetUpdateView.as_view(), name='subnet_edit'),
    path('subnets/<int:pk>/delete/', SubnetDeleteView.as_view(), name='subnet_delete'),
    
    # IP地址管理
    path('ips/', IPAddressListView.as_view(), name='ip_list'),
    path('ips/<int:pk>/allocate/', ip_allocate, name='ip_allocate'),
    path('ips/<int:pk>/release/', ip_release, name='ip_release'),
    path('ips/<int:pk>/<str:status>/', ip_set_status, name='ip_set_status'),
    path('subnets/<int:subnet_pk>/batch-allocate/', batch_allocate, name='batch_allocate'),

    # ===== 网络探测功能 =====
    path('scan/', scan_index, name='scan_index'),
    path('scan/create/', create_scan_task, name='scan_create'),
    path('scan/<int:pk>/', scan_task_detail, name='scan_detail'),
    path('scan/<int:pk>/execute/', execute_scan, name='scan_execute'),
    path('scan/<int:pk>/progress/', get_scan_progress, name='scan_progress'),
    path('scan/<int:pk>/cancel/', cancel_scan, name='scan_cancel'),
    path('scan/<int:pk>/export/', export_scan_results, name='scan_export'),
    path('scan/<int:pk>/delete/', delete_scan_task, name='scan_delete'),
    
    # 快速探测 (AJAX)
    path('api/ping/', quick_ping, name='quick_ping'),
    path('api/port-scan/', quick_port_scan, name='quick_port_scan'),
    path('api/allocate-ip/', quick_allocate_ip, name='quick_allocate_ip'),
    
    # 探测历史和规则
    path('scan/history/', probe_history, name='probe_history'),
    path('scan/rules/', discovery_rules, name='discovery_rules'),
    path('scan/topology/', live_topology, name='live_topology'),
]
