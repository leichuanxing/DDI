from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from common.responses import success_response
from common.viewsets import UnifiedModelViewSet
from .models import User, Role, Permission, LoginLog
from .serializers import UserSerializer, RoleSerializer, PermissionSerializer, LoginSerializer, ChangePasswordSerializer, LoginLogSerializer


def client_ip(request):
    return request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0]


@require_http_methods(['GET', 'POST'])
def web_login_view(request):
    if request.user.is_authenticated:
        return redirect(request.GET.get('next') or 'dashboard')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        next_url = request.POST.get('next') or request.GET.get('next') or '/'
        user = authenticate(request, username=username, password=password)
        if user and user.is_active:
            login(request, user)
            LoginLog.objects.create(
                username=user.username,
                user=user,
                request_ip=client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                result='success',
            )
            return redirect(next_url)
        LoginLog.objects.create(
            username=username,
            request_ip=client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            result='failed',
            error_message='用户名或密码错误，或用户已禁用',
        )
        messages.error(request, '用户名或密码错误，或用户已禁用')
    return render(request, 'accounts/login.html', {'next': request.GET.get('next', '/')})


def web_logout_view(request):
    logout(request)
    return redirect('accounts-login')


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def login_view(request):
    serializer = LoginSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data['user']
    login(request, user)
    refresh = RefreshToken.for_user(user)
    LoginLog.objects.create(username=user.username, user=user, request_ip=client_ip(request), user_agent=request.META.get('HTTP_USER_AGENT', ''), result='success')
    return success_response({'access': str(refresh.access_token), 'refresh': str(refresh), 'user': UserSerializer(user).data})


@api_view(['POST'])
def logout_view(request):
    logout(request)
    return success_response(message='退出成功')


@api_view(['GET'])
def profile_view(request):
    return success_response(UserSerializer(request.user).data)


@api_view(['POST'])
def change_password_view(request):
    serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    request.user.set_password(serializer.validated_data['new_password'])
    request.user.save(update_fields=['password'])
    return success_response(message='密码修改成功')


class UserViewSet(UnifiedModelViewSet):
    queryset = User.objects.all().order_by('-id')
    serializer_class = UserSerializer
    filterset_fields = ['is_active', 'is_superuser']
    search_fields = ['username', 'real_name', 'email', 'mobile']


class RoleViewSet(UnifiedModelViewSet):
    queryset = Role.objects.prefetch_related('permissions').all().order_by('-id')
    serializer_class = RoleSerializer
    search_fields = ['name', 'code']


class PermissionViewSet(UnifiedModelViewSet):
    http_method_names = ['get', 'head', 'options']
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_module = 'system'


class LoginLogViewSet(UnifiedModelViewSet):
    http_method_names = ['get', 'head', 'options']
    queryset = LoginLog.objects.all()
    serializer_class = LoginLogSerializer
    filterset_fields = ['username', 'result']
    search_fields = ['username', 'request_ip']
    permission_module = 'audit'
