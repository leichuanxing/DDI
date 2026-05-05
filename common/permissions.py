from rest_framework.permissions import BasePermission
from accounts.models import Permission


ACTION_MAP = {
    'list': 'view',
    'retrieve': 'view',
    'create': 'add',
    'update': 'change',
    'partial_update': 'change',
    'destroy': 'delete',
    'export_excel': 'export',
    'import_excel': 'import',
    'push_to_pdns': 'deploy',
    'sync_from_pdns': 'deploy',
    'config_set': 'deploy',
    'config_reload': 'reload',
    'logs': 'view_log',
}

MODULE_MAP = {
    'accounts': 'system',
    'ipam': 'ipam',
    'dns': 'dns',
    'dhcp': 'dhcp',
    'tasks': 'deploy',
    'audit': 'audit',
    'system': 'monitor',
}


class RBACPermission(BasePermission):
    message = '权限不足'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not Permission.objects.exists():
            return True
        module = getattr(view, 'permission_module', None)
        if not module:
            app_label = getattr(getattr(view, 'queryset', None), 'model', None)
            module = MODULE_MAP.get(getattr(getattr(app_label, '_meta', None), 'app_label', ''), '')
        action = getattr(view, 'permission_action', None) or ACTION_MAP.get(getattr(view, 'action', ''), 'view')
        if not module:
            return True
        code = f'{module}.{action}'
        return user.roles.filter(permissions__code=code).exists()
