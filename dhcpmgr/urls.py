from django.urls import path
from .views import (
    PoolListView, PoolDetailView, PoolCreateView, PoolUpdateView, PoolDeleteView,
    toggle_pool_status,
    ExclusionCreateView, ExclusionUpdateView, ExclusionDeleteView,
    LeaseListView, lease_create, lease_release, check_expired_leases,
    dhcp_service_page, dhcp_service_start, dhcp_service_stop, dhcp_service_status
)

app_name = 'dhcpmgr'

urlpatterns = [
    # DHCP地址池管理
    path('pools/', PoolListView.as_view(), name='pool_list'),
    path('pools/create/', PoolCreateView.as_view(), name='pool_create'),
    path('pools/<int:pk>/', PoolDetailView.as_view(), name='pool_detail'),
    path('pools/<int:pk>/edit/', PoolUpdateView.as_view(), name='pool_edit'),
    path('pools/<int:pk>/delete/', PoolDeleteView.as_view(), name='pool_delete'),
    path('pools/<int:pk>/toggle/', toggle_pool_status, name='toggle_pool'),
    
    # 排除地址管理
    path('exclusions/create/', ExclusionCreateView.as_view(), name='exclusion_create'),
    path('exclusions/<int:pk>/edit/', ExclusionUpdateView.as_view(), name='exclusion_edit'),
    path('exclusions/<int:pk>/delete/', ExclusionDeleteView.as_view(), name='exclusion_delete'),
    
    # 租约管理
    path('leases/', LeaseListView.as_view(), name='lease_list'),
    path('leases/create/', lease_create, name='lease_create'),
    path('leases/<int:pk>/release/', lease_release, name='lease_release'),
    path('leases/check-expired/', check_expired_leases, name='check_expired'),
    
    # DHCP服务管理
    path('service/', dhcp_service_page, name='service'),
    path('api/service/start/', dhcp_service_start, name='service_start'),
    path('api/service/stop/', dhcp_service_stop, name='service_stop'),
    path('api/service/status/', dhcp_service_status, name='service_status'),
]
