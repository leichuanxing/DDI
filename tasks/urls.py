from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SystemTaskViewSet
router=DefaultRouter(); router.register('', SystemTaskViewSet)
urlpatterns=[path('', include(router.urls))]
