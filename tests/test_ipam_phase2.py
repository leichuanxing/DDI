from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from ipam.forms import SubnetForm
from ipam.models import IPAddress, Region, Subnet, VLAN
from ipam.services import IPAddressService, NetworkScanService, SubnetService


class IPAMPhase2Tests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="IDC", code="idc")
        self.vlan = VLAN.objects.create(vlan_id=31, name="vlan31", region=self.region, gateway="192.168.31.1")

    def test_create_region_and_vlan(self):
        self.assertGreaterEqual(Region.objects.count(), 1)
        self.assertEqual(VLAN.objects.count(), 1)
        self.assertEqual(self.vlan.region, self.region)

    def test_subnet_cidr_gateway_and_overlap_validation(self):
        subnet = Subnet(
            name="业务网段",
            cidr="192.168.31.0/24",
            gateway="192.168.31.1",
            region=self.region,
            vlan=self.vlan,
        )
        subnet.full_clean()
        subnet.save()

        form = SubnetForm(
            data={
                "name": "重叠子网",
                "cidr": "192.168.31.128/25",
                "gateway": "192.168.31.129",
                "region": self.region.id,
                "vlan": self.vlan.id,
                "usage": "办公网",
                "status": "enabled",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cidr", form.errors)

    def test_generate_ips_marks_gateway(self):
        subnet = Subnet.objects.create(
            name="办公网",
            cidr="192.168.31.0/29",
            gateway="192.168.31.1",
            region=self.region,
            vlan=self.vlan,
        )
        result = SubnetService.generate_ips(subnet)
        self.assertEqual(result["created"], 6)
        gateway_ip = IPAddress.objects.get(subnet=subnet, ip_address="192.168.31.1")
        self.assertEqual(gateway_ip.status, "gateway")
        self.assertEqual(gateway_ip.bind_type, "manual")

    def test_allocate_and_release_ip(self):
        subnet = Subnet.objects.create(
            name="测试网",
            cidr="192.168.50.0/29",
            gateway="192.168.50.1",
            region=self.region,
        )
        SubnetService.generate_ips(subnet)
        ip_obj = IPAddress.objects.get(subnet=subnet, ip_address="192.168.50.2")
        IPAddressService.allocate_ip(
            ip_obj,
            {
                "hostname": "host01",
                "device_name": "switch-01",
                "owner": "alice",
                "mac_address": "00:11:22:33:44:55",
                "bind_type": "static",
                "description": "核心交换机",
            },
        )
        ip_obj.refresh_from_db()
        subnet.refresh_from_db()
        self.assertEqual(ip_obj.status, "used")
        self.assertEqual(ip_obj.hostname, "host01")
        self.assertEqual(subnet.used_ips, 2)

        IPAddressService.release_ip(ip_obj)
        ip_obj.refresh_from_db()
        subnet.refresh_from_db()
        self.assertEqual(ip_obj.status, "available")
        self.assertEqual(ip_obj.hostname, "")
        self.assertEqual(subnet.used_ips, 1)

    def test_vlan_delete_restriction(self):
        Subnet.objects.create(
            name="生产子网",
            cidr="10.0.0.0/24",
            gateway="10.0.0.1",
            region=self.region,
            vlan=self.vlan,
        )
        with self.assertRaises(Exception):
            self.vlan.delete()

    @patch("ipam.services.subprocess.run")
    def test_single_ping_and_subnet_scan(self, mocked_run):
        mocked_run.return_value.returncode = 0
        mocked_run.return_value.stdout = "64 bytes from 192.168.31.2"
        mocked_run.return_value.stderr = ""
        subnet = Subnet.objects.create(
            name="扫描网段",
            cidr="192.168.60.0/30",
            gateway="192.168.60.1",
            region=self.region,
        )
        SubnetService.generate_ips(subnet)
        result = NetworkScanService.ping("192.168.60.2")
        self.assertEqual(result["status"], "online")
        records = NetworkScanService.scan_subnet(subnet)
        self.assertEqual(len(records), 2)

    def test_gateway_cannot_release(self):
        subnet = Subnet.objects.create(
            name="网关网段",
            cidr="172.16.10.0/29",
            gateway="172.16.10.1",
            region=self.region,
        )
        SubnetService.generate_ips(subnet)
        gateway_ip = IPAddress.objects.get(subnet=subnet, ip_address="172.16.10.1")
        with self.assertRaises(ValidationError):
            IPAddressService.release_ip(gateway_ip)
