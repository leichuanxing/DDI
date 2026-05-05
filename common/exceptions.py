from rest_framework.views import exception_handler
from .responses import error_response


def unified_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return error_response(str(exc), code=exc.__class__.__name__.upper(), status=500)
    details = response.data if isinstance(response.data, dict) else {'detail': response.data}
    message = details.get('detail') or details.get('non_field_errors') or '请求参数或权限校验失败'
    if isinstance(message, list):
        message = message[0]
    return error_response(str(message), code=getattr(exc, 'default_code', 'ERROR').upper(), details=details, status=response.status_code)
