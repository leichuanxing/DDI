from rest_framework.decorators import action, api_view

from common.audit import write_audit
from common.responses import error_response, success_response
from common.viewsets import UnifiedModelViewSet
from tasks.serializers import SystemTaskSerializer
from tasks.services import TaskService

from .models import DNSChangeLog, DNSProviderConfig, DNSRecord, DNSZone
from .serializers import DNSChangeLogSerializer, DNSProviderConfigSerializer, DNSRecordSerializer, DNSZoneSerializer
from .services import DNSService


@api_view(['GET', 'PUT'])
def config_view(request):
    cfg = DNSService.ensure_config()
    if request.method == 'GET':
        return success_response(DNSProviderConfigSerializer(cfg).data)
    serializer = DNSProviderConfigSerializer(cfg, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return success_response(serializer.data)


@api_view(['POST'])
def test_connection_view(request):
    return success_response(DNSService.client().test_connection())


class DNSZoneViewSet(UnifiedModelViewSet):
    queryset = DNSZone.objects.all().order_by('-id')
    serializer_class = DNSZoneSerializer
    filterset_fields = ['kind', 'status', 'dnssec']
    search_fields = ['name', 'description']
    permission_module = 'dns'

    def destroy(self, request, *args, **kwargs):
        zone = self.get_object()
        result = DNSService.delete_zone_remote(zone, user=request.user, request=request)
        if not result.get('success'):
            return error_response(
                message=result.get('message') or 'PowerDNS Zone 删除失败，本地 Zone 已保留',
                code=result.get('code') or 'DNS_ZONE_DELETE_FAILED',
                details=result,
                status=400,
            )
        zone.delete()
        return success_response(message='DNS Zone 已从 PowerDNS 和本地删除')

    @action(detail=False, methods=['post'], url_path='sync-from-pdns')
    def sync_from_pdns(self, request):
        task = TaskService.enqueue('dns_zone_sync', 'ddi-pdns', {}, request.user)
        return success_response(SystemTaskSerializer(task).data, message='PowerDNS Zone 同步任务已创建', status=202)

    @action(detail=True, methods=['post'], url_path='push-to-pdns')
    def push_to_pdns(self, request, pk=None):
        task = TaskService.enqueue('dns_zone_push', 'ddi-pdns', {'zone_id': self.get_object().id}, request.user)
        return success_response(SystemTaskSerializer(task).data, message='DNS Zone 下发任务已创建', status=202)


class DNSRecordViewSet(UnifiedModelViewSet):
    queryset = DNSRecord.objects.select_related('zone').all().order_by('-id')
    serializer_class = DNSRecordSerializer
    filterset_fields = ['zone', 'record_type', 'disabled']
    search_fields = ['name', 'content', 'comment']
    permission_module = 'dns'

    def destroy(self, request, *args, **kwargs):
        record = self.get_object()
        result = DNSService.client().delete_record(
            DNSService.canonical_zone_name(record.zone.name),
            DNSService.canonical_record_name(record.name, record.zone.name),
            record.record_type,
        )
        if not result.get('success'):
            return error_response(
                message=result.get('message') or 'PowerDNS 记录删除失败，本地记录已保留',
                code=result.get('code') or 'DNS_RECORD_DELETE_FAILED',
                details=result,
                status=400,
            )
        DNSChangeLog.objects.create(
            zone=record.zone,
            record=record,
            action='delete_record_remote',
            payload={'name': record.name, 'type': record.record_type, 'content': record.content},
            result='success',
            operator=request.user if request.user.is_authenticated else None,
        )
        write_audit(request, action='dns_record_delete', module='dns', obj=record, payload={'remote': result})
        record.delete()
        return success_response(message='DNS 记录已从 PowerDNS 和本地删除')

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        serializer = DNSRecordSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(serializer.data)

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        deleted = 0
        failures = []
        for record in DNSRecord.objects.select_related('zone').filter(id__in=request.data.get('ids', [])):
            result = DNSService.client().delete_record(
                DNSService.canonical_zone_name(record.zone.name),
                DNSService.canonical_record_name(record.name, record.zone.name),
                record.record_type,
            )
            if result.get('success'):
                DNSChangeLog.objects.create(
                    zone=record.zone,
                    record=record,
                    action='bulk_delete_record_remote',
                    payload={'name': record.name, 'type': record.record_type, 'content': record.content},
                    result='success',
                    operator=request.user if request.user.is_authenticated else None,
                )
                record.delete()
                deleted += 1
            else:
                failures.append({'id': record.id, 'name': record.name, 'message': result.get('message')})
        if failures:
            return error_response(
                message='部分 DNS 记录删除失败，失败记录已保留',
                code='DNS_RECORD_BULK_DELETE_PARTIAL_FAILED',
                details={'deleted': deleted, 'failures': failures},
                status=400,
            )
        return success_response({'deleted': deleted}, message='DNS 记录已从 PowerDNS 和本地删除')

    @action(detail=False, methods=['post'], url_path='sync-from-pdns')
    def sync_from_pdns(self, request):
        task = TaskService.enqueue('dns_record_sync', 'ddi-pdns', {'zone_id': request.data.get('zone_id')}, request.user)
        return success_response(SystemTaskSerializer(task).data, message='DNS 记录同步任务已创建', status=202)

    @action(detail=False, methods=['post'])
    def compare(self, request):
        zone = DNSZone.objects.filter(pk=request.data.get('zone_id')).first()
        return success_response(DNSService.compare_records(zone))

    @action(detail=True, methods=['post'], url_path='push-to-pdns')
    def push_to_pdns(self, request, pk=None):
        task = TaskService.enqueue('dns_record_push', 'ddi-pdns', {'record_id': self.get_object().id, 'changetype': 'REPLACE'}, request.user)
        return success_response(SystemTaskSerializer(task).data, message='DNS 记录下发任务已创建', status=202)


class DNSChangeLogViewSet(UnifiedModelViewSet):
    http_method_names = ['get', 'head', 'options']
    queryset = DNSChangeLog.objects.all()
    serializer_class = DNSChangeLogSerializer
    permission_module = 'audit'
