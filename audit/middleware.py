from common.audit import write_audit


class AuditContextMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/') and request.method in ('POST','PUT','PATCH','DELETE'):
            module = request.path.split('/')[2] if len(request.path.split('/')) > 2 else 'api'
            payload = request.POST.dict() if request.POST else {}
            write_audit(request, action=request.method.lower(), module=module, payload=payload, response_status=response.status_code, result='success' if response.status_code < 400 else 'failed')
        return response
