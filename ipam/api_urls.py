from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import IPAddressViewSet, RegionViewSet, SubnetViewSet, VLANViewSet, network_ping, network_subnet_scan


router = DefaultRouter()
router.register("regions", RegionViewSet, basename="api-ipam-regions")
router.register("vlans", VLANViewSet, basename="api-ipam-vlans")
router.register("subnets", SubnetViewSet, basename="api-ipam-subnets")
router.register("ips", IPAddressViewSet, basename="api-ipam-ips")


urlpatterns = [
    path("", include(router.urls)),
    path("network-scan/ping/", network_ping, name="api-ipam-network-ping"),
    path("network-scan/subnet/", network_subnet_scan, name="api-ipam-network-subnet"),
]
