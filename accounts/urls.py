from django.urls import path
from .views import (
    login_view, logout_view,
    UserListView, UserCreateView, UserUpdateView, UserDeleteView,
    RoleListView, LoginLogListView, reset_password
)

app_name = 'accounts'

urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/create/', UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', UserDeleteView.as_view(), name='user_delete'),
    path('users/<int:pk>/reset-password/', reset_password, name='reset_password'),
    path('roles/', RoleListView.as_view(), name='role_list'),
    path('login-log/', LoginLogListView.as_view(), name='login_log'),
]
