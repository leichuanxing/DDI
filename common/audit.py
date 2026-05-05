from audit.models import AuditLog


def get_client_ip(request):
    if not request:
        return ''
    return request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0]


def write_audit(request=None, *, action, module, obj=None, object_type='', object_id='', object_name='', result='success', error_message='', payload=None, response_status=None, username=''):
    user = getattr(request, 'user', None) if request else None
    if user and getattr(user, 'is_authenticated', False):
        username = user.username
        user_id = user.id
    else:
        user_id = None
    if obj is not None:
        object_type = object_type or obj.__class__.__name__
        object_id = object_id or getattr(obj, 'pk', '') or ''
        object_name = object_name or str(obj)
    try:
        return AuditLog.objects.create(
            username=username,
            user_id=user_id,
            action=action,
            module=module,
            object_type=object_type,
            object_id=str(object_id) if object_id else '',
            object_name=str(object_name) if object_name else '',
            request_ip=get_client_ip(request) or None,
            request_method=getattr(request, 'method', '') if request else '',
            request_path=getattr(request, 'path', '') if request else '',
            request_payload=payload or {},
            response_status=response_status,
            result=result,
            error_message=error_message or '',
        )
    except Exception:
        return None
