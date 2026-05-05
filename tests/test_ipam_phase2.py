from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model
from ipam.models import AddressSpace, Subnet, IPAddressHistory
from ipam.services import IPAMService


class IPAMPhase2Tests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='operator', password='x')
        self.space = AddressSpace.objects.create(name='生产网络', code='prod')

    def test_subnet_overlap_detection(self):
        Subnet.objects.create(address_space=self.space, cidr='10.0.0.0/24')
        subnet = Subnet(address_space=self.space, cidr='10.0.0.128/25')
        with self.assertRaises(ValidationError):
            subnet.full_clean()

    def test_generate_ips_skips_gateway_and_tracks_status_history(self):
        subnet = Subnet.objects.create(address_space=self.space, cidr='192.0.2.0/29', gateway='192.0.2.1')
        result = IPAMService.generate_ips(subnet)
        self.assertEqual(result['created'], 5)
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(subnet.ip_addresses.filter(ip_address='192.0.2.1').exists())

        ip_obj = subnet.ip_addresses.get(ip_address='192.0.2.2')
        IPAMService.allocate(ip_obj, self.user, hostname='host01', mac_address='00:11:22:33:44:55', owner='alice')
        ip_obj.refresh_from_db()
        self.assertEqual(ip_obj.status, 'used')
        self.assertEqual(ip_obj.hostname, 'host01')
        self.assertEqual(IPAddressHistory.objects.filter(ip_address=ip_obj, action='allocate').count(), 1)

        IPAMService.release(ip_obj, self.user)
        ip_obj.refresh_from_db()
        self.assertEqual(ip_obj.status, 'available')
        self.assertEqual(ip_obj.hostname, '')

    def test_utilization_alerts(self):
        subnet = Subnet.objects.create(address_space=self.space, cidr='198.51.100.0/30')
        IPAMService.generate_ips(subnet)
        first = subnet.ip_addresses.first()
        IPAMService.allocate(first, self.user)
        row = IPAMService.subnet_utilization(subnet)
        self.assertEqual(row['total'], 2)
        self.assertEqual(row['used'], 1)
        self.assertEqual(row['utilization'], 50.0)
        self.assertEqual(row['alert'], 'normal')
