from rest_framework.response import Response


def success_response(data=None, message='操作成功', code='SUCCESS', status=200):
    return Response({'success': True, 'code': code, 'message': message, 'data': data or {}}, status=status)


def error_response(message='操作失败', code='ERROR', details=None, status=400):
    return Response({'success': False, 'code': code, 'message': message, 'details': details or {}}, status=status)
