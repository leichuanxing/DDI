from rest_framework import serializers

from .models import IPAddress, Region, Subnet, VLAN


class RegionSerializer(serializers.ModelSerializer):
    subnet_count = serializers.IntegerField(read_only=True)
    vlan_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Region
        fields = "__all__"


class VLANSerializer(serializers.ModelSerializer):
    subnet_count = serializers.IntegerField(read_only=True)
    region_name = serializers.CharField(source="region.name", read_only=True)

    class Meta:
        model = VLAN
        fields = "__all__"


class SubnetSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source="region.name", read_only=True)
    vlan_name_display = serializers.CharField(source="vlan.name", read_only=True)
    utilization_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = Subnet
        fields = "__all__"


class IPAddressSerializer(serializers.ModelSerializer):
    subnet_cidr = serializers.CharField(source="subnet.cidr", read_only=True)

    class Meta:
        model = IPAddress
        fields = "__all__"
