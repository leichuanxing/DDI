from django.db.models import Count
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import RBACPermission

from .forms import IPAllocateForm, NetworkScanForm, SubnetScanForm
from .models import IPAddress, NetworkScanRecord, Region, Subnet, VLAN
from .serializers import IPAddressSerializer, RegionSerializer, SubnetSerializer, VLANSerializer
from .services import IPAddressService, NetworkScanService, SubnetService


class RegionViewSet(viewsets.ModelViewSet):
    queryset = Region.objects.annotate(
        subnet_count=Count("subnets", distinct=True),
        vlan_count=Count("vlans", distinct=True),
    ).order_by("id")
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated, RBACPermission]


class VLANViewSet(viewsets.ModelViewSet):
    queryset = VLAN.objects.select_related("region").annotate(subnet_count=Count("subnets", distinct=True)).order_by("region__name", "vlan_id")
    serializer_class = VLANSerializer
    permission_classes = [IsAuthenticated, RBACPermission]


class SubnetViewSet(viewsets.ModelViewSet):
    queryset = Subnet.objects.select_related("region", "vlan").order_by("cidr")
    serializer_class = SubnetSerializer
    permission_classes = [IsAuthenticated, RBACPermission]

    @action(detail=True, methods=["post"], url_path="generate-ips")
    def generate_ips(self, request, pk=None):
        subnet = self.get_object()
        result = SubnetService.generate_ips(subnet)
        return Response({"success": True, "message": "IP 地址生成完成。", "data": result})


class IPAddressViewSet(
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = IPAddress.objects.select_related("subnet").order_by("ip_address")
    serializer_class = IPAddressSerializer
    permission_classes = [IsAuthenticated, RBACPermission]

    @action(detail=True, methods=["post"], url_path="allocate")
    def allocate(self, request, pk=None):
        ip_obj = self.get_object()
        form = IPAllocateForm(request.data)
        form.is_valid(raise_exception=True)
        ip_obj = IPAddressService.allocate_ip(ip_obj, form.cleaned_data, user=request.user)
        return Response({"success": True, "message": "IP 分配成功。", "data": IPAddressSerializer(ip_obj).data})

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        ip_obj = self.get_object()
        ip_obj = IPAddressService.release_ip(ip_obj, user=request.user)
        return Response({"success": True, "message": "IP 已释放。", "data": IPAddressSerializer(ip_obj).data})

    @action(detail=True, methods=["post"], url_path="ping")
    def ping(self, request, pk=None):
        ip_obj = self.get_object()
        result = IPAddressService.ping_ip(ip_obj.ip_address)
        IPAddressService.record_ping_result(ip_obj, result)
        return Response({"success": True, "message": "探测完成。", "data": result})


@api_view(["POST"])
@permission_classes([IsAuthenticated, RBACPermission])
def network_ping(request):
    form = NetworkScanForm(request.data)
    if not form.is_valid():
        return Response({"success": False, "message": "请输入合法的 IPv4 地址。", "errors": form.errors}, status=status.HTTP_400_BAD_REQUEST)
    result = NetworkScanService.ping(form.cleaned_data["ip_address"])
    record = NetworkScanRecord.objects.create(
        ip_address=form.cleaned_data["ip_address"],
        status=result["status"],
        response_time=result.get("response_time", ""),
        error_message=result.get("error_message", ""),
    )
    return Response({"success": True, "message": "单 IP 探测完成。", "data": {"record_id": record.id, **result}}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated, RBACPermission])
def network_subnet_scan(request):
    form = SubnetScanForm(request.data)
    if not form.is_valid():
        return Response({"success": False, "message": "请选择要探测的子网。", "errors": form.errors}, status=status.HTTP_400_BAD_REQUEST)
    subnet = form.cleaned_data["subnet"]
    records = NetworkScanService.scan_subnet(subnet)
    return Response({"success": True, "message": "子网批量探测完成。", "data": {"count": len(records)}})
