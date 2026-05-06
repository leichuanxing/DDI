from django.contrib import admin
from django.urls import path, include
from accounts.views import web_login_view, web_logout_view
from system.views import dashboard, dns_service_page, web_create, web_edit, web_list
urlpatterns = [
    path('login/', web_login_view, name='web-login'),
    path('accounts/login/', web_login_view, name='accounts-login'),
    path('logout/', web_logout_view, name='web-logout'),
    path('', dashboard, name='dashboard'),
    path('dashboard/', dashboard, name='dashboard-page'),
    path('ipam/', include('ipam.urls')),
    path('ui/dns/service/', dns_service_page, name='dns-service-page'),
    path('ui/<str:section>/<str:page>/new/', web_create, name='web-create'),
    path('ui/<str:section>/<str:page>/<int:pk>/edit/', web_edit, name='web-edit'),
    path('ui/<str:section>/<str:page>/', web_list, name='web-list'),
    path('admin/', admin.site.urls),
    path('api/', include('accounts.urls')),
    path('api/ipam/', include('ipam.api_urls')),
    path('api/dns/', include('dns.urls')),
    path('api/dhcp/', include('dhcp.urls')),
    path('api/tasks/', include('tasks.urls')),
    path('api/audit-logs/', include('audit.urls')),
    path('api/health/', include('system.urls')),
]
