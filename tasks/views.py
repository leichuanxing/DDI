from rest_framework.decorators import action
from common.responses import success_response
from common.viewsets import UnifiedModelViewSet
from .models import SystemTask, TaskLog
from .serializers import SystemTaskSerializer, TaskLogSerializer
from .services import TaskService
class SystemTaskViewSet(UnifiedModelViewSet):
    http_method_names = ['get','post','head','options']
    queryset = SystemTask.objects.all()
    serializer_class = SystemTaskSerializer
    filterset_fields = ['task_type','target_service','status']
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        old = self.get_object(); task = TaskService.enqueue(old.task_type, old.target_service, old.request_payload, request.user); return success_response(SystemTaskSerializer(task).data)
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None): return success_response(TaskLogSerializer(self.get_object().logs.all(), many=True).data)
