from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DNSZoneViewSet, DNSRecordViewSet, DNSChangeLogViewSet, DNSQueryLogViewSet, config_view, query_log_ingest_view, test_connection_view
router = DefaultRouter(); router.register('zones', DNSZoneViewSet); router.register('records', DNSRecordViewSet); router.register('change-logs', DNSChangeLogViewSet); router.register('query-logs', DNSQueryLogViewSet)
urlpatterns = [path('config/', config_view), path('test-connection/', test_connection_view), path('query-logs/ingest/', query_log_ingest_view), path('', include(router.urls))]
