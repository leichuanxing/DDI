from rest_framework.decorators import action, api_view

from common.responses import success_response
from common.viewsets import UnifiedModelViewSet
from tasks.serializers import SystemTaskSerializer
from tasks.services import TaskService

from .models import DHCPLease, DHCPOption, DHCPPool, DHCPProviderConfig, DHCPReservation, DHCPSubnet
from .serializers import DHCPLeaseSerializer, DHCPOptionSerializer, DHCPPoolSerializer, DHCPProviderConfigSerializer, DHCPReservationSerializer, DHCPSubnetSerializer
from .services import DHCPService


@api_view(['GET', 'PUT'])
def config_view(request):
    cfg = DHCPService.ensure_config()
    if request.method == 'GET':
        return success_response(DHCPProviderConfigSerializer(cfg).data)
    serializer = DHCPProviderConfigSerializer(cfg, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return success_response(serializer.data)


@api_view(['POST'])
def test_connection_view(request):
    return success_response(DHCPService.client().test_connection())


@api_view(['GET'])
def status_view(request):
    return success_response(DHCPService.client().status_get())


@api_view(['GET'])
def config_current_view(request):
    return success_response(DHCPService.client().config_get('dhcp4'))


@api_view(['POST'])
def config_test_view(request):
    task = TaskService.enqueue('dhcp_config_test', 'ddi-kea', {'service': request.data.get('service', 'dhcp4')}, request.user)
    return success_response(SystemTaskSerializer(task).data, message='DHCP 配置测试任务已创建', status=202)


@api_view(['POST'])
def config_set_view(request):
    task = TaskService.enqueue('dhcp_config_apply', 'ddi-kea', {'service': request.data.get('service', 'dhcp4')}, request.user)
    return success_response(SystemTaskSerializer(task).data, message='DHCP 配置下发任务已创建', status=202)


@api_view(['POST'])
def config_reload_view(request):
    task = TaskService.enqueue('dhcp_config_reload', 'ddi-kea', {'service': request.data.get('service', 'dhcp4')}, request.user)
    return success_response(SystemTaskSerializer(task).data, message='DHCP 配置重载任务已创建', status=202)


class DHCPSubnetViewSet(UnifiedModelViewSet):
    queryset = DHCPSubnet.objects.all().order_by('-id')
    serializer_class = DHCPSubnetSerializer
    filterset_fields = ['status', 'ipam_subnet']
    search_fields = ['subnet', 'description']
    permission_module = 'dhcp'


class DHCPPoolViewSet(UnifiedModelViewSet):
    queryset = DHCPPool.objects.select_related('dhcp_subnet').all().order_by('-id')
    serializer_class = DHCPPoolSerializer
    filterset_fields = ['dhcp_subnet', 'status']
    permission_module = 'dhcp'


class DHCPReservationViewSet(UnifiedModelViewSet):
    queryset = DHCPReservation.objects.select_related('dhcp_subnet').all().order_by('-id')
    serializer_class = DHCPReservationSerializer
    filterset_fields = ['dhcp_subnet', 'status']
    search_fields = ['ip_address', 'mac_address', 'hostname', 'client_id']
    permission_module = 'dhcp'

    def perform_create(self, serializer):
        reservation = serializer.save()
        DHCPService.mark_reservation_ipam(reservation, self.request.user)

    def perform_destroy(self, instance):
        release_ipam = self.request.query_params.get('release_ipam', 'false').lower() == 'true'
        if release_ipam:
            DHCPService.release_reservation_ipam(instance, self.request.user)
        instance.delete()


class DHCPOptionViewSet(UnifiedModelViewSet):
    queryset = DHCPOption.objects.all().order_by('-id')
    serializer_class = DHCPOptionSerializer
    filterset_fields = ['scope_type', 'scope_id', 'option_code']
    permission_module = 'dhcp'


class DHCPLeaseViewSet(UnifiedModelViewSet):
    http_method_names = ['get', 'post', 'head', 'options']
    queryset = DHCPLease.objects.all().order_by('-updated_at')
    serializer_class = DHCPLeaseSerializer
    filterset_fields = ['ip_address', 'mac_address', 'hostname', 'subnet_id', 'state']
    permission_module = 'dhcp'

    @action(detail=False, methods=['post'])
    def sync(self, request):
        return success_response(DHCPService.sync_leases(request), message='Kea 租约同步完成')

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        task = TaskService.enqueue('dhcp_lease_release', 'ddi-kea', {'lease_id': self.get_object().id, 'service': 'dhcp4'}, request.user)
        return success_response(SystemTaskSerializer(task).data, message='租约释放任务已创建', status=202)

    @action(detail=True, methods=['post'], url_path='convert-to-reservation')
    def convert_to_reservation(self, request, pk=None):
        lease = self.get_object()
        subnet = DHCPSubnet.objects.filter(subnet_id=lease.subnet_id).first()
        reservation = DHCPReservation.objects.create(dhcp_subnet=subnet, ip_address=lease.ip_address, mac_address=lease.mac_address, hostname=lease.hostname, status='enabled') if subnet else None
        if reservation:
            DHCPService.mark_reservation_ipam(reservation, request.user)
        return success_response(DHCPReservationSerializer(reservation).data if reservation else {'detail': '未找到匹配 DHCP 子网'})
