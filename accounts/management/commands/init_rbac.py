from django.core.management.base import BaseCommand

from accounts.models import Permission


PERMISSIONS = {
    'system': ['view', 'add', 'change', 'delete'],
    'user': ['view', 'add', 'change', 'delete'],
    'role': ['view', 'add', 'change', 'delete'],
    'ipam': ['view', 'add', 'change', 'delete', 'import', 'export'],
    'dns': ['view', 'add', 'change', 'delete', 'import', 'export', 'deploy'],
    'dhcp': ['view', 'add', 'change', 'delete', 'import', 'export', 'deploy', 'reload'],
    'deploy': ['view', 'add', 'change', 'delete', 'view_log', 'deploy', 'reload'],
    'audit': ['view', 'export'],
    'monitor': ['view', 'add'],
}


class Command(BaseCommand):
    help = 'Initialize DDI RBAC permission codes'

    def handle(self, *args, **options):
        created = 0
        for module, actions in PERMISSIONS.items():
            for action in actions:
                _, was_created = Permission.objects.get_or_create(
                    module=module,
                    action=action,
                    code=f'{module}.{action}',
                    defaults={'description': f'{module} {action}'},
                )
                created += 1 if was_created else 0
        self.stdout.write(self.style.SUCCESS(f'RBAC permissions ready, created={created}'))
