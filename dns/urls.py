from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DNSZoneViewSet, DNSRecordViewSet, DNSChangeLogViewSet, config_view, test_connection_view
router = DefaultRouter(); router.register('zones', DNSZoneViewSet); router.register('records', DNSRecordViewSet); router.register('change-logs', DNSChangeLogViewSet)
urlpatterns = [path('config/', config_view), path('test-connection/', test_connection_view), path('', include(router.urls))]
