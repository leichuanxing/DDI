from rest_framework import serializers
from .models import SystemConfig, ServiceHealthCheck
class SystemConfigSerializer(serializers.ModelSerializer):
    class Meta: model = SystemConfig; fields = '__all__'
class ServiceHealthCheckSerializer(serializers.ModelSerializer):
    class Meta: model = ServiceHealthCheck; fields = '__all__'
