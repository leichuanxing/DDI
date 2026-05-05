from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AddressSpaceViewSet, SubnetViewSet, IPAddressViewSet, IPAddressHistoryViewSet, utilization_view
router = DefaultRouter()
router.register('address-spaces', AddressSpaceViewSet)
router.register('subnets', SubnetViewSet)
router.register('ip-addresses', IPAddressViewSet)
router.register('histories', IPAddressHistoryViewSet)
urlpatterns = [path('', include(router.urls)), path('utilization/', utilization_view)]
