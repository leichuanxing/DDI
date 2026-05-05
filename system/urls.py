from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SystemConfigViewSet, health_view, services_view, check_now_view, dashboard_stats
router=DefaultRouter(); router.register('configs', SystemConfigViewSet)
urlpatterns=[
    path('', health_view, name='health'),
    path('stats/', dashboard_stats, name='dashboard-stats'),
    path('services/', services_view, name='health-services'),
    path('check-now/', check_now_view, name='check-now'),
    path('', include(router.urls)),
]
