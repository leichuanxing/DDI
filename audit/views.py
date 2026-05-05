import csv

from django.http import HttpResponse
from rest_framework.decorators import api_view

from common.viewsets import UnifiedModelViewSet

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(UnifiedModelViewSet):
    http_method_names = ['get', 'head', 'options']
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    filterset_fields = ['username', 'module', 'action', 'result']
    search_fields = ['username', 'object_name', 'request_path', 'error_message']
    permission_module = 'audit'


@api_view(['GET'])
def export_view(request):
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="audit_logs.csv"'
    writer = csv.writer(resp)
    writer.writerow(['id', 'username', 'action', 'module', 'object_type', 'object_id', 'object_name', 'result', 'request_ip', 'created_at'])
    for log in AuditLog.objects.all()[:10000]:
        writer.writerow([log.id, log.username, log.action, log.module, log.object_type, log.object_id, log.object_name, log.result, log.request_ip, log.created_at])
    return resp
