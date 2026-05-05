from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
router=DefaultRouter(); router.register('subnets', DHCPSubnetViewSet); router.register('pools', DHCPPoolViewSet); router.register('reservations', DHCPReservationViewSet); router.register('options', DHCPOptionViewSet); router.register('leases', DHCPLeaseViewSet)
urlpatterns=[path('config/', config_view), path('test-connection/', test_connection_view), path('status/', status_view), path('config-current/', config_current_view), path('config-test/', config_test_view), path('config-set/', config_set_view), path('config-reload/', config_reload_view), path('', include(router.urls))]
