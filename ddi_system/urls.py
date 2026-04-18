"""
URL configuration for ddi_system project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('ipam/', include('ipam.urls')),
    path('dns/', include('dnsmgr.urls')),
    path('dhcp/', include('dhcpmgr.urls')),
    path('devices/', include('devices.urls')),
    path('logs/', include('logs.urls')),
    path('', include('dashboard.urls')),  # 首页
]
