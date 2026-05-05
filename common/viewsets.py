from common.audit import write_audit
from common.permissions import RBACPermission
from rest_framework import viewsets
from rest_framework.response import Response


class UnifiedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [RBACPermission]

    def finalize_response(self, request, response, *args, **kwargs):
        if isinstance(response, Response) and not getattr(response, 'exception', False):
            if not isinstance(response.data, dict) or 'success' not in response.data:
                response.data = {'success': True, 'code': 'SUCCESS', 'message': '操作成功', 'data': response.data if response.data is not None else {}}
        return super().finalize_response(request, response, *args, **kwargs)

    def perform_create(self, serializer):
        obj = serializer.save()
        write_audit(self.request, action='create', module=obj._meta.app_label, obj=obj, payload=self.request.data)

    def perform_update(self, serializer):
        obj = serializer.save()
        write_audit(self.request, action='update', module=obj._meta.app_label, obj=obj, payload=self.request.data)

    def perform_destroy(self, instance):
        write_audit(self.request, action='delete', module=instance._meta.app_label, obj=instance)
        instance.delete()
