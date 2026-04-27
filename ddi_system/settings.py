"""
DDI管理系统 - Django全局配置
包含应用注册、中间件、数据库、认证、国际化、静态文件等核心配置
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 安全密钥（生产环境必须更换）
SECRET_KEY = 'django-insecure-ddi-system-dev-key-change-in-production-2024'

# 调试模式（生产环境必须设为False）
DEBUG = True

# 允许的主机头（生产环境应限制具体域名/IP）
ALLOWED_HOSTS = ['*']

# ========== 应用注册 ==========
INSTALLED_APPS = [
    # Django 内置应用
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # DDI 业务应用
    'accounts.apps.AccountsConfig',    # 账户管理（用户/角色/登录日志）
    'dashboard.apps.DashboardConfig',  # 仪表盘首页
    'ipam.apps.IpamConfig',            # IP地址管理（区域/VLAN/子网/IP/网络探测）
    'devices.apps.DevicesConfig',      # 设备管理（主机/接口/IP关联）
    'logs.apps.LogsConfig',            # 审计日志
    'dns.apps.DnsConfig',              # DNS管理（BIND9配置/Zone/记录/ACL/View/发布/审计）
]

# ========== 中间件 ==========
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',          # 安全头
    'django.contrib.sessions.middleware.SessionMiddleware',  # 会话管理
    'django.middleware.common.CommonMiddleware',              # 通用处理
    'django.middleware.csrf.CsrfViewMiddleware',              # CSRF防护
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # 认证
    'django.contrib.messages.middleware.MessageMiddleware',   # 消息框架
    'django.middleware.clickjacking.XFrameOptionsMiddleware',  # 点击劫持防护
]

ROOT_URLCONF = 'ddi_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ddi_system.wsgi.application'

# ========== 数据库配置（默认SQLite3，支持迁移至MySQL/PostgreSQL）==========
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ========== 密码验证策略 ==========
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# ========== 国际化配置 ==========
LANGUAGE_CODE = 'zh-hans'   # 简体中文
TIME_ZONE = 'Asia/Shanghai'  # 上海时区
USE_I18N = True             # 启用国际化
USE_TZ = True               # 启用时区

# ========== 静态文件配置 ==========
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']   # 开发时静态文件目录
STATIC_ROOT = BASE_DIR / 'staticfiles'      # collectstatic输出目录

# ========== 媒体文件配置 ==========
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ========== 认证配置 ==========
# 登录/登出跳转地址
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'    # 登录后跳转仪表盘
LOGOUT_REDIRECT_URL = '/accounts/login/'  # 登出后跳转登录页

# 自定义用户模型（扩展了角色、部门等字段）
AUTH_USER_MODEL = 'accounts.User'

# ========== 分页配置 ==========
PAGE_SIZE = 20

# ========== IP地址状态选项（全局共用） ==========
IP_STATUS_CHOICES = (
    ('available', '空闲'),
    ('allocated', '已分配'),
    ('reserved', '保留'),
    ('conflict', '冲突'),
    ('disabled', '禁用'),
)

# ========== 设备类型选项（全局共用） ==========
DEVICE_TYPES = [
    '服务器', 'PC', '笔记本', '打印机', '交换机', 
    '路由器', '防火墙', '摄像头', 'AP', '其他'
]
