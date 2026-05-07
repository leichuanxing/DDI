import re

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import DHCPLease, DHCPOption, DHCPPool, DHCPProviderConfig, DHCPReservation, DHCPSubnet


MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')


class DHCPProviderConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DHCPProviderConfig
        fields = '__all__'
        extra_kwargs = {'password': {'write_only': True, 'required': False}}

    def validate(self, attrs):
        instance = self.instance or DHCPProviderConfig()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        return attrs


class DHCPSubnetSerializer(serializers.ModelSerializer):
    pool_count = serializers.IntegerField(source='pools.count', read_only=True)

    class Meta:
        model = DHCPSubnet
        fields = '__all__'

    def validate(self, attrs):
        instance = self.instance or DHCPSubnet()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        attrs['subnet'] = instance.subnet
        return attrs


class DHCPPoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = DHCPPool
        fields = '__all__'

    def validate(self, attrs):
        instance = self.instance or DHCPPool()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        return attrs


class DHCPReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DHCPReservation
        fields = '__all__'

    def validate_mac_address(self, value):
        if value and not MAC_RE.match(value):
            raise serializers.ValidationError('MAC 地址格式错误，示例：00:11:22:33:44:55')
        return value.lower().replace('-', ':') if value else value

    def validate(self, attrs):
        instance = self.instance or DHCPReservation()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        attrs['mac_address'] = instance.mac_address
        return attrs


class DHCPOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DHCPOption
        fields = '__all__'

    def validate(self, attrs):
        instance = self.instance or DHCPOption()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        attrs['scope_id'] = instance.scope_id
        attrs['option_name'] = instance.option_name
        attrs['option_value'] = instance.option_value
        return attrs


class DHCPLeaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = DHCPLease
        fields = '__all__'
