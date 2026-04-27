"""DNS管理模块 - URL路由配置"""

from django.urls import path
from .views import (
    # 仪表盘
    DashboardView,
    # 服务管理
    service_manage, api_service_action,
    # 配置同步
    config_sync_view, api_sync_execute,
    # 全局配置
    GlobalOptionEdit, global_option_preview,
    # ACL
    AclListView, AclCreateView, AclUpdateView, AclDeleteView, acl_detail,
    # View
    ViewListView, ViewCreateView, ViewUpdateView, ViewDeleteView, view_preview,
    # Zone
    ZoneListView, ZoneCreateView, ZoneUpdateView, ZoneDeleteView, zone_detail,
    zone_check, zone_reload, zone_preview_config,
    # 记录
    RecordListView, RecordCreateView, RecordUpdateView, RecordDeleteView,
    record_batch_import, record_batch_export,
    # 转发
    forward_list, forward_create, forward_update, forward_delete, api_test_forwarder,
    # 主从同步
    sync_status_list, api_trigger_sync,
    # 日志中心
    dns_log_center,
    # 发布中心
    publish_list, publish_detail, publish_confirm, publish_history, api_quick_publish,
    # 备份回滚
    backup_list, backup_detail, confirm_rollback, api_manual_backup,
    # 审计日志
    audit_log_list, api_audit_detail,
)

app_name = 'dns'

urlpatterns = [
    # ========== 1. DNS仪表盘 ==========
    path('', DashboardView.as_view(), name='dashboard'),

    # ========== 2. DNS服务管理 ==========
    path('service/', service_manage, name='service'),
    path('api/service-action/', api_service_action, name='api_service_action'),

    # ========== 3. 配置同步 ==========
    path('sync-config/', config_sync_view, name='config_sync'),
    path('api/sync-execute/', api_sync_execute, name='api_sync_execute'),

    # ========== 4. 全局配置 ==========
    path('options/', GlobalOptionEdit.as_view(), name='options'),
    path('options/preview/', global_option_preview, name='global_option_preview'),

    # ========== 5. ACL管理 ==========
    path('acl/', AclListView.as_view(), name='acl_list'),
    path('acl/create/', AclCreateView.as_view(), name='acl_create'),
    path('acl/<int:pk>/', acl_detail, name='acl_detail'),
    path('acl/<int:pk>/edit/', AclUpdateView.as_view(), name='acl_edit'),
    path('acl/<int:pk>/delete/', AclDeleteView.as_view(), name='acl_delete'),

    # ========== 6. View管理 ==========
    path('views/', ViewListView.as_view(), name='view_list'),
    path('views/create/', ViewCreateView.as_view(), name='view_create'),
    path('views/<int:pk>/edit/', ViewUpdateView.as_view(), name='view_edit'),
    path('views/<int:pk>/delete/', ViewDeleteView.as_view(), name='view_delete'),
    path('views/<int:pk>/preview/', view_preview, name='view_preview'),

    # ========== 7. 区域管理 ==========
    path('zones/', ZoneListView.as_view(), name='zone_list'),
    path('zones/create/', ZoneCreateView.as_view(), name='zone_create'),
    path('zones/<int:pk>/', zone_detail, name='zone_detail'),
    path('zones/<int:pk>/edit/', ZoneUpdateView.as_view(), name='zone_edit'),
    path('zones/<int:pk>/delete/', ZoneDeleteView.as_view(), name='zone_delete'),
    path('zones/<int:pk>/check/', zone_check, name='zone_check'),
    path('zones/<int:pk>/reload/', zone_reload, name='zone_reload'),
    path('zones/<int:pk>/preview/', zone_preview_config, name='zone_preview'),

    # ========== 8. 资源记录管理 ==========
    path('records/', RecordListView.as_view(), name='record_list'),
    path('records/create/', RecordCreateView.as_view(), name='record_create'),
    path('records/<int:pk>/edit/', RecordUpdateView.as_view(), name='record_edit'),
    path('records/<int:pk>/delete/', RecordDeleteView.as_view(), name='record_delete'),
    path('records/batch-import/', record_batch_import, name='batch_import'),
    path('records/batch-export/', record_batch_export, name='batch_export'),

    # ========== 9. 转发管理 ==========
    path('forwards/', forward_list, name='forward_list'),
    path('forwards/create/', forward_create, name='forward_create'),
    path('forwards/<int:pk>/edit/', forward_update, name='forward_edit'),
    path('forwards/<int:pk>/delete/', forward_delete, name='forward_delete'),
    path('api/test-forwarder/', api_test_forwarder, name='test_forwarder'),

    # ========== 10. 主从同步 ==========
    path('sync-status/', sync_status_list, name='sync_status'),
    path('api/trigger-sync/', api_trigger_sync, name='trigger_sync'),

    # ========== 11. 日志中心 ==========
    path('log-center/', dns_log_center, name='log_center'),

    # ========== 12. 发布中心 ==========
    path('publish/', publish_list, name='publish_list'),
    path('publish/<int:pk>/', publish_detail, name='publish_detail'),
    path('publish/<int:pk>/confirm/', publish_confirm, name='publish_confirm'),
    path('publish/history/', publish_history, name='publish_history'),
    path('api/quick-publish/', api_quick_publish, name='api_quick_publish'),

    # ========== 13. 备份回滚 ==========
    path('backups/', backup_list, name='backup_list'),
    path('backups/<int:pk>/', backup_detail, name='backup_detail'),
    path('backups/<int:pk>/rollback/', confirm_rollback, name='confirm_rollback'),
    path('api/manual-backup/', api_manual_backup, name='api_manual_backup'),

    # ========== 14. 审计日志 ==========
    path('audit/', audit_log_list, name='audit'),
    path('api/audit-detail/<int:pk>/', api_audit_detail, name='api_audit_detail'),
]
