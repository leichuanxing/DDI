import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'change-me-in-production')
DEBUG = os.getenv('DJANGO_DEBUG', 'false').lower() == 'true'
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')
CSRF_TRUSTED_ORIGINS = [x for x in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if x]

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'rest_framework.authtoken', 'django_filters',
    'accounts', 'ipam', 'dns', 'dhcp', 'tasks', 'audit', 'system',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'audit.middleware.AuditContextMiddleware',
]

ROOT_URLCONF = 'ddi_system.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug', 'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'ddi_system.wsgi.application'
ASGI_APPLICATION = 'ddi_system.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('MYSQL_DATABASE', 'ddi_system'),
        'USER': os.getenv('MYSQL_USER', 'ddi'),
        'PASSWORD': os.getenv('MYSQL_PASSWORD', 'ddi_password'),
        'HOST': os.getenv('MYSQL_HOST', 'ddi-mysql'),
        'PORT': os.getenv('MYSQL_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4'},
    }
}
if os.getenv('SQLITE_DATABASE'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.getenv('SQLITE_DATABASE')}}


AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', 'zh-hans')
TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Shanghai')
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('common.permissions.RBACPermission',),
    'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend', 'rest_framework.filters.SearchFilter', 'rest_framework.filters.OrderingFilter'),
    'EXCEPTION_HANDLER': 'common.exceptions.unified_exception_handler',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': int(os.getenv('DEFAULT_PAGE_SIZE', '20')),
}
SIMPLE_JWT = {'ACCESS_TOKEN_LIFETIME': timedelta(hours=8), 'REFRESH_TOKEN_LIFETIME': timedelta(days=7)}

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://ddi-web:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

PDNS_API_URL = os.getenv('PDNS_API_URL', 'http://ddi-pdns:8081')
PDNS_API_KEY = os.getenv('PDNS_API_KEY', 'ddi-pdns-key')
KEA_API_URL = os.getenv('KEA_API_URL', 'http://ddi-kea:8000')
KEA_LEASE_DB_HOST = os.getenv('KEA_LEASE_DB_HOST', os.getenv('MYSQL_HOST', 'ddi-mysql'))
KEA_LEASE_DB_PORT = int(os.getenv('KEA_LEASE_DB_PORT', os.getenv('MYSQL_PORT', '3306')))
KEA_LEASE_DB_NAME = os.getenv('KEA_LEASE_DB_NAME', 'kea')
KEA_LEASE_DB_USER = os.getenv('KEA_LEASE_DB_USER', os.getenv('MYSQL_USER', 'ddi'))
KEA_LEASE_DB_PASSWORD = os.getenv('KEA_LEASE_DB_PASSWORD', os.getenv('MYSQL_PASSWORD', 'ddi_password'))
CONFIG_ENCRYPTION_KEY = os.getenv('CONFIG_ENCRYPTION_KEY', '')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'standard': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'}},
    'root': {'handlers': ['console'], 'level': os.getenv('LOG_LEVEL', 'INFO')},
}


# Four-container deployment keeps Celery inside ddi-web; the filesystem broker avoids adding Redis/RabbitMQ.
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'filesystem://')
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'data_folder_in': os.getenv('CELERY_FS_IN', str(BASE_DIR / 'celery_queue' / 'out')),
    'data_folder_out': os.getenv('CELERY_FS_OUT', str(BASE_DIR / 'celery_queue' / 'out')),
    'data_folder_processed': os.getenv('CELERY_FS_PROCESSED', str(BASE_DIR / 'celery_queue' / 'processed')),
}
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'rpc://')

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
