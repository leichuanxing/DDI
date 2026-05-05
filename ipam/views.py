from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.decorators import action, api_view
from common.responses import success_response
from common.viewsets import UnifiedModelViewSet
from .models import AddressSpace, Subnet, IPAddress, IPAddressHistory
from .serializers import AddressSpaceSerializer, SubnetSerializer, IPAddressSerializer, IPAddressHistorySerializer, IPAllocateSerializer, IPReserveSerializer
from .services import IPAMService


def raise_drf_validation(exc):
    raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)

class AddressSpaceViewSet(UnifiedModelViewSet):
    queryset = AddressSpace.objects.all().order_by('-id')
    serializer_class = AddressSpaceSerializer
    search_fields = ['name', 'code']

class SubnetViewSet(UnifiedModelViewSet):
    queryset = Subnet.objects.select_related('address_space').all().order_by('-id')
    serializer_class = SubnetSerializer
    filterset_fields = ['address_space', 'vlan_id', 'usage_type', 'location', 'status']
    search_fields = ['cidr', 'vlan_name', 'description']

    def perform_create(self, serializer):
        super().perform_create(serializer)
        IPAMService.generate_ips(serializer.instance)

    @action(detail=True, methods=['post'], url_path='generate-ips')
    def generate_ips(self, request, pk=None):
        return success_response(IPAMService.generate_ips(self.get_object()))

    @action(detail=True, methods=['get'])
    def utilization(self, request, pk=None):
        return success_response(IPAMService.subnet_utilization(self.get_object()) or {})

    @action(detail=False, methods=['get'], url_path='export-excel')
    def export_excel(self, request):
        output = IPAMService.export_subnets()
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="ipam_subnets.xlsx"'
        return response

    @action(detail=False, methods=['post'], url_path='import-excel')
    def import_excel(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            raise serializers.ValidationError({'file': '请上传 Excel 文件'})
        return success_response(IPAMService.import_subnets(file_obj))

class IPAddressViewSet(UnifiedModelViewSet):
    queryset = IPAddress.objects.select_related('subnet').all().order_by('ip_address')
    serializer_class = IPAddressSerializer
    filterset_fields = ['status', 'subnet', 'hostname', 'mac_address', 'department']
    search_fields = ['ip_address', 'hostname', 'mac_address', 'owner', 'department']

    @action(detail=True, methods=['post'])
    def allocate(self, request, pk=None):
        serializer = IPAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ip = IPAMService.allocate(self.get_object(), request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise_drf_validation(exc)
        return success_response(IPAddressSerializer(ip).data)

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        try:
            ip = IPAMService.release(self.get_object(), request.user)
        except DjangoValidationError as exc:
            raise_drf_validation(exc)
        return success_response(IPAddressSerializer(ip).data)

    @action(detail=True, methods=['post'])
    def reserve(self, request, pk=None):
        serializer = IPReserveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ip = IPAMService.reserve(self.get_object(), request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise_drf_validation(exc)
        return success_response(IPAddressSerializer(ip).data)

    @action(detail=True, methods=['post'])
    def disable(self, request, pk=None):
        ip = IPAMService.set_status(self.get_object(), 'disabled', request.user, 'disable')
        return success_response(IPAddressSerializer(ip).data)

    @action(detail=True, methods=['get'])
    def histories(self, request, pk=None):
        data = IPAddressHistorySerializer(self.get_object().histories.all(), many=True).data
        return success_response(data)

    @action(detail=False, methods=['get'], url_path='export-excel')
    def export_excel(self, request):
        output = IPAMService.export_ip_addresses()
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="ipam_addresses.xlsx"'
        return response

    @action(detail=False, methods=['post'], url_path='import-excel')
    def import_excel(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            raise serializers.ValidationError({'file': '请上传 Excel 文件'})
        return success_response(IPAMService.import_ip_addresses(file_obj, request.user))

class IPAddressHistoryViewSet(UnifiedModelViewSet):
    http_method_names = ['get', 'head', 'options']
    queryset = IPAddressHistory.objects.select_related('ip_address').all()
    serializer_class = IPAddressHistorySerializer
    filterset_fields = ['ip_address', 'action']

@api_view(['GET'])
def utilization_view(request):
    return success_response(IPAMService.utilization())
