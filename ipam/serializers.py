import re
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import AddressSpace, Subnet, IPAddress, IPAddressHistory

class AddressSpaceSerializer(serializers.ModelSerializer):
    subnet_count = serializers.IntegerField(source='subnets.count', read_only=True)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = AddressSpace
        fields = '__all__'

    def get_stats(self, obj):
        total_subnets = obj.subnets.count()
        total_ips = IPAddress.objects.filter(subnet__address_space=obj).count()
        available_ips = IPAddress.objects.filter(subnet__address_space=obj, status='available').count()
        return {
            'subnet_count': total_subnets,
            'ip_total': total_ips,
            'ip_available': available_ips,
            'ip_used': total_ips - available_ips,
        }

class SubnetSerializer(serializers.ModelSerializer):
    utilization = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Subnet
        fields = '__all__'

    def validate(self, attrs):
        instance = self.instance or Subnet()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        attrs['cidr'] = instance.cidr
        attrs['netmask'] = instance.netmask
        return attrs

    def get_utilization(self, obj):
        total = obj.ip_addresses.count()
        available = obj.ip_addresses.filter(status='available').count()
        used_total = total - available
        return round((used_total / total) * 100, 2) if total else 0

class IPAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = IPAddress
        fields = '__all__'

    def validate_mac_address(self, value):
        if value and not re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', value):
            raise serializers.ValidationError('MAC 地址格式错误，示例：00:11:22:33:44:55')
        return value.lower().replace('-', ':') if value else value

    def validate(self, attrs):
        instance = self.instance or IPAddress()
        for key, value in attrs.items():
            setattr(instance, key, value)
        if instance.subnet_id:
            try:
                instance.full_clean()
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        return attrs

class IPAddressHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = IPAddressHistory
        fields = '__all__'


class IPAllocateSerializer(serializers.Serializer):
    hostname = serializers.CharField(required=False, allow_blank=True, max_length=255)
    mac_address = serializers.CharField(required=False, allow_blank=True, max_length=32)
    usage_type = serializers.CharField(required=False, allow_blank=True, max_length=64)
    owner = serializers.CharField(required=False, allow_blank=True, max_length=64)
    department = serializers.CharField(required=False, allow_blank=True, max_length=64)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_mac_address(self, value):
        return IPAddressSerializer().validate_mac_address(value)


class IPReserveSerializer(IPAllocateSerializer):
    pass
