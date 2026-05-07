import ipaddress
import re

from rest_framework import serializers

from .models import DNSChangeLog, DNSProviderConfig, DNSQueryLog, DNSRecord, DNSZone


ZONE_RE = re.compile(r'^(?=.{1,253}\.?$)([a-zA-Z0-9_][a-zA-Z0-9_-]{0,62}\.)+[a-zA-Z]{2,}\.?$')


class DNSProviderConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DNSProviderConfig
        fields = '__all__'
        extra_kwargs = {'api_key': {'write_only': True, 'required': False}}


class DNSZoneSerializer(serializers.ModelSerializer):
    record_count = serializers.IntegerField(source='records.count', read_only=True)

    class Meta:
        model = DNSZone
        fields = '__all__'

    def validate_name(self, value):
        value = value.strip().lower()
        if not value.endswith('.'):
            value = value + '.'
        if not ZONE_RE.match(value):
            raise serializers.ValidationError('Zone 名称格式错误，示例：example.com.')
        qs = DNSZone.objects.filter(name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Zone 已存在')
        return value


class DNSRecordSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model = DNSRecord
        fields = '__all__'

    def validate(self, attrs):
        zone = attrs.get('zone') or getattr(self.instance, 'zone', None)
        name = (attrs.get('name') or getattr(self.instance, 'name', '')).strip()
        record_type = attrs.get('record_type') or getattr(self.instance, 'record_type', '')
        content = (attrs.get('content') or getattr(self.instance, 'content', '')).strip()
        ttl = attrs.get('ttl', getattr(self.instance, 'ttl', 3600))
        priority = attrs.get('priority', getattr(self.instance, 'priority', None))

        if ttl < 0:
            raise serializers.ValidationError({'ttl': 'TTL 不能小于 0'})
        if zone and name and not name.endswith('.'):
            name = f'{name}.{zone.name}'
            attrs['name'] = name
        if record_type in ('A', 'AAAA'):
            try:
                ip = ipaddress.ip_address(content)
            except ValueError:
                raise serializers.ValidationError({'content': f'{record_type} 记录内容必须是合法 IP 地址'})
            if record_type == 'A' and ip.version != 4:
                raise serializers.ValidationError({'content': 'A 记录必须是 IPv4 地址'})
            if record_type == 'AAAA' and ip.version != 6:
                raise serializers.ValidationError({'content': 'AAAA 记录必须是 IPv6 地址'})
        if record_type == 'CNAME' and not content.endswith('.'):
            raise serializers.ValidationError({'content': 'CNAME 记录内容应为 FQDN 并以点结尾'})
        if record_type == 'MX' and priority is None:
            raise serializers.ValidationError({'priority': 'MX 记录必须设置优先级'})
        qs = DNSRecord.objects.filter(zone=zone, name=name, record_type=record_type, content=content)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('DNS 记录重复')
        return attrs


class DNSChangeLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DNSChangeLog
        fields = '__all__'


class DNSQueryLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DNSQueryLog
        fields = '__all__'
        read_only_fields = ['created_at']
        extra_kwargs = {'query_time': {'required': False}}

    def validate_query_name(self, value):
        value = (value or '').strip().lower()
        if not value:
            raise serializers.ValidationError('查询域名不能为空')
        return value

    def validate_query_type(self, value):
        return (value or '').strip().upper()
