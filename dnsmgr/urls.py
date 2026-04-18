from django.urls import path
from .views import (
    ZoneListView, ZoneDetailView, ZoneCreateView, ZoneUpdateView, ZoneDeleteView,
    RecordListView, RecordCreateView, RecordUpdateView, RecordDeleteView,
    toggle_record_status, dns_service, query_log, clear_query_log,
    dns_resolve_test, service_probe_index, service_probe,
    probe_task_list, probe_task_create, probe_task_update, probe_task_delete,
)

app_name = 'dnsmgr'

urlpatterns = [
    # DNS服务管理
    path('service/', dns_service, name='dns_service'),
    path('service/resolve-test/', dns_resolve_test, name='dns_resolve_test'),

    # DNS解析日志
    path('query-log/', query_log, name='query_log'),
    path('query-log/clear/', clear_query_log, name='query_log_clear'),

    # DNS区域管理
    path('zones/', ZoneListView.as_view(), name='zone_list'),
    path('zones/create/', ZoneCreateView.as_view(), name='zone_create'),
    path('zones/<int:pk>/', ZoneDetailView.as_view(), name='zone_detail'),
    path('zones/<int:pk>/edit/', ZoneUpdateView.as_view(), name='zone_edit'),
    path('zones/<int:pk>/delete/', ZoneDeleteView.as_view(), name='zone_delete'),
    
    # DNS记录管理
    path('records/', RecordListView.as_view(), name='record_list'),
    path('records/create/', RecordCreateView.as_view(), name='record_create'),
    path('records/<int:pk>/edit/', RecordUpdateView.as_view(), name='record_edit'),
    path('records/<int:pk>/delete/', RecordDeleteView.as_view(), name='record_delete'),
    path('records/<int:pk>/toggle/', toggle_record_status, name='toggle_record'),

    # 服务探测
    path('probe/', service_probe_index, name='service_probe'),
    path('probe/api/', service_probe, name='service_probe_api'),

    # 探测任务CRUD（持久化）
    path('probe/tasks/', probe_task_list, name='probe_task_list'),
    path('probe/tasks/create/', probe_task_create, name='probe_task_create'),
    path('probe/tasks/<int:pk>/', probe_task_update, name='probe_task_update'),
    path('probe/tasks/<int:pk>/delete/', probe_task_delete, name='probe_task_delete'),
]
