from django.urls import path

from . import views


urlpatterns = [
    path("regions/", views.region_list, name="ipam-region-list"),
    path("regions/add/", views.region_add, name="ipam-region-add"),
    path("regions/<int:pk>/edit/", views.region_edit, name="ipam-region-edit"),
    path("regions/<int:pk>/delete/", views.region_delete, name="ipam-region-delete"),

    path("vlans/", views.vlan_list, name="ipam-vlan-list"),
    path("vlans/add/", views.vlan_add, name="ipam-vlan-add"),
    path("vlans/<int:pk>/edit/", views.vlan_edit, name="ipam-vlan-edit"),
    path("vlans/<int:pk>/delete/", views.vlan_delete, name="ipam-vlan-delete"),

    path("subnets/", views.subnet_list, name="ipam-subnet-list"),
    path("subnets/add/", views.subnet_add, name="ipam-subnet-add"),
    path("subnets/<int:pk>/detail/", views.subnet_detail, name="ipam-subnet-detail"),
    path("subnets/<int:pk>/edit/", views.subnet_edit, name="ipam-subnet-edit"),
    path("subnets/<int:pk>/delete/", views.subnet_delete, name="ipam-subnet-delete"),
    path("subnets/<int:pk>/generate-ips/", views.subnet_generate_ips, name="ipam-subnet-generate-ips"),
    path(
        "subnets/<int:subnet_pk>/allocate-ip/",
        views.subnet_ip_allocate,
        name="ipam-subnet-ip-allocate",
    ),

    path("ips/", views.ip_list, name="ipam-ip-list"),
    path("ips/<int:pk>/allocate/", views.ip_allocate, name="ipam-ip-allocate"),
    path("ips/<int:pk>/release/", views.ip_release, name="ipam-ip-release"),
    path("ips/<int:pk>/edit/", views.ip_edit, name="ipam-ip-edit"),
    path("ips/<int:pk>/delete/", views.ip_delete, name="ipam-ip-delete"),
    path("ips/<int:pk>/ping/", views.ip_ping, name="ipam-ip-ping"),

    path("network-scan/", views.network_scan, name="ipam-network-scan"),
    path("network-scan/tasks/ping/new/", views.network_probe_ping_new, name="ipam-probe-ping-new"),
    path("network-scan/tasks/port/new/", views.network_probe_port_new, name="ipam-probe-port-new"),
    path("network-scan/tasks/arp/new/", views.network_probe_arp_new, name="ipam-probe-arp-new"),
    path(
        "network-scan/tasks/<int:pk>/delete/",
        views.network_probe_task_delete,
        name="ipam-probe-task-delete",
    ),
    path("network-scan/tasks/<int:pk>/", views.network_probe_task_detail, name="ipam-probe-task-detail"),
    path("network-scan/ping/", views.network_scan_ping, name="ipam-network-scan-ping"),
    path("network-scan/subnet/", views.network_scan_subnet, name="ipam-network-scan-subnet"),
]
