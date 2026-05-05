from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuditLogViewSet, export_view
router=DefaultRouter(); router.register('', AuditLogViewSet)
urlpatterns=[path('export/', export_view), path('', include(router.urls))]
