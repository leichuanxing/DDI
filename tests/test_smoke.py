from django.test import TestCase
from django.contrib.auth import get_user_model
from ipam.models import AddressSpace, Subnet
from ipam.services import IPAMService

class SmokeTests(TestCase):
    def test_create_user_and_generate_ips(self):
        user = get_user_model().objects.create_user(username='u1', password='x')
        space = AddressSpace.objects.create(name='默认地址空间', code='default')
        subnet = Subnet.objects.create(address_space=space, cidr='192.0.2.0/30', gateway='192.0.2.1')
        result = IPAMService.generate_ips(subnet)
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['skipped'], 1)
        self.assertTrue(user.check_password('x'))
