from django.conf import settings


def ddi_release(request):
    return {'ddi_version': getattr(settings, 'DDI_VERSION', 'dev')}
