from django.urls import path
from .views import (
    DeviceListView, DeviceDetailView, DeviceCreateView, DeviceUpdateView, DeviceDeleteView,
    link_device_to_ip
)

app_name = 'devices'

urlpatterns = [
    path('', DeviceListView.as_view(), name='device_list'),
    path('create/', DeviceCreateView.as_view(), name='device_create'),
    path('<int:pk>/', DeviceDetailView.as_view(), name='device_detail'),
    path('<int:pk>/edit/', DeviceUpdateView.as_view(), name='device_edit'),
    path('<int:pk>/delete/', DeviceDeleteView.as_view(), name='device_delete'),
    path('<int:device_pk>/link-ip/<int:ip_pk>/', link_device_to_ip, name='link_ip'),
]
