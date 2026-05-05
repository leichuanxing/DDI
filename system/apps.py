from django.apps import AppConfig

class SystemConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'system'
    verbose_name = '系统配置与健康检查'
