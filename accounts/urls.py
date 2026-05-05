from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, RoleViewSet, PermissionViewSet, LoginLogViewSet, login_view, logout_view, profile_view, change_password_view

router = DefaultRouter()
router.register('users', UserViewSet)
router.register('roles', RoleViewSet)
router.register('permissions', PermissionViewSet)
router.register('login-logs', LoginLogViewSet)

urlpatterns = [
    path('auth/login/', login_view),
    path('auth/logout/', logout_view),
    path('auth/profile/', profile_view),
    path('auth/change-password/', change_password_view),
    path('', include(router.urls)),
]
