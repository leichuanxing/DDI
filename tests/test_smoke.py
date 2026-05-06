from django.contrib.auth import get_user_model
from django.test import TestCase

from ipam.models import Region, Subnet
from ipam.services import SubnetService


class SmokeTests(TestCase):
    def test_create_user_and_ipam_records(self):
        user = get_user_model().objects.create_user(username="u1", password="x")
        region = Region.objects.create(name="默认区域-测试", code="default-smoke")
        subnet = Subnet.objects.create(name="默认子网", region=region, cidr="192.0.2.0/30", gateway="192.0.2.1")
        result = SubnetService.generate_ips(subnet)
        self.assertEqual(result["created"], 2)
        self.assertTrue(user.check_password("x"))
