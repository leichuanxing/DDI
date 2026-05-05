from rest_framework import serializers
from .models import SystemTask, TaskLog
class SystemTaskSerializer(serializers.ModelSerializer):
    class Meta: model = SystemTask; fields = '__all__'
class TaskLogSerializer(serializers.ModelSerializer):
    class Meta: model = TaskLog; fields = '__all__'
