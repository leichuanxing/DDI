"""
ASGI config for ddi_system project.
"""

import os

from django.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ddi_system.settings')

application = get_asgi_application()
