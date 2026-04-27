"""
账户管理模块 - 视图函数
提供用户登录/登出、用户CRUD、角色管理、登录日志查询等功能
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views.generic import CreateView, UpdateView, DeleteView, ListView
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils.decorators import method_decorator
from .models import User, Role, LoginLog
from .forms import LoginForm, UserCreateForm, UserEditForm, RoleForm
from common.logger import log_operation


def login_view(request):
    """登录视图 - 处理用户认证，记录登录成功/失败日志"""
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # 记录登录成功日志
            LoginLog.objects.create(
                user=user,
                username=user.username,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                status='success',
                message='登录成功'
            )
            # 更新最后登录IP
            user.last_login_ip = request.META.get('REMOTE_ADDR')
            user.save(update_fields=['last_login_ip'])
            
            log_operation(user, '登录', 'accounts', 'login', '', str(user.username))
            return redirect('dashboard:index')
        else:
            # 记录登录失败日志（用于安全审计）
            LoginLog.objects.create(
                user=None,
                username=request.POST.get('username', ''),
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                status='failed',
                message='用户名或密码错误'
            )
    else:
        form = LoginForm()
    return render(request, 'accounts/login.html', {'form': form})


@login_required
def logout_view(request):
    """登出视图 - 记录退出日志后重定向到登录页"""
    log_operation(request.user, '退出', 'accounts', 'logout', '', str(request.user.username))
    logout(request)
    return redirect('accounts:login')


@method_decorator([login_required], name='dispatch')
class UserListView(ListView):
    """用户列表视图 - 支持按用户名/姓名/邮箱搜索和按角色筛选"""
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 20
    
    def get_queryset(self):
        """支持搜索和角色筛选"""
        queryset = super().get_queryset()
        search = self.request.GET.get('search', '')
        role = self.request.GET.get('role', '')
        if search:
            # 同时在用户名、姓名、邮箱中搜索
            queryset = queryset.filter(username__icontains=search) | \
                       queryset.filter(real_name__icontains=search) | \
                       queryset.filter(email__icontains=search)
        if role:
            queryset = queryset.filter(role__code=role)
        return queryset
    
    def get_context_data(self, **kwargs):
        """将搜索条件和角色列表传递给模板"""
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['role'] = self.request.GET.get('role', '')
        context['roles'] = Role.objects.all()
        return context


@method_decorator([login_required], name='dispatch')
class UserCreateView(CreateView):
    """创建用户视图"""
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    
    def form_valid(self, form):
        """表单验证通过后，记录操作日志"""
        response = super().form_valid(form)
        messages.success(self.request, f'用户 {self.object.username} 创建成功')
        log_operation(self.request.user, '新增', 'accounts', 'user', '', 
                     f"创建用户: {self.object.username}")
        return response


@method_decorator([login_required], name='dispatch')
class UserUpdateView(UpdateView):
    """编辑用户视图 - 支持修改密码（可选）"""
    model = User
    form_class = UserEditForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    
    def form_valid(self, form):
        """处理密码修改（仅当用户填写了新密码时才修改）"""
        new_pwd = form.cleaned_data.get('new_password1')
        if new_pwd:
            self.object.set_password(new_pwd)  # 使用set_password自动加密
            self.object.save()
        response = super().form_valid(form)
        messages.success(self.request, f'用户 {self.object.username} 更新成功' +
                         ('（密码已修改）' if new_pwd else ''))
        log_operation(self.request.user, '修改', 'accounts', 'user', '',
                     f"更新用户: {self.object.username}" + ('(含密码修改)' if new_pwd else ''))
        return response


@method_decorator([login_required], name='dispatch')
class UserDeleteView(DeleteView):
    """删除用户视图"""
    model = User
    template_name = 'accounts/user_confirm_delete.html'
    success_url = reverse_lazy('accounts:user_list')
    
    def delete(self, request, *args, **kwargs):
        """删除前记录操作日志"""
        obj = self.get_object()
        log_operation(request.user, '删除', 'accounts', 'user', '',
                     f"删除用户: {obj.username}")
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'用户 {obj.username} 已删除')
        return response


@method_decorator([login_required], name='dispatch')
class RoleListView(ListView):
    """角色列表视图"""
    model = Role
    template_name = 'accounts/role_list.html'
    context_object_name = 'roles'


@method_decorator([login_required], name='dispatch')
class LoginLogListView(ListView):
    """登录日志列表视图 - 支持按用户名搜索和按状态筛选"""
    model = LoginLog
    template_name = 'accounts/login_log.html'
    context_object_name = 'logs'
    paginate_by = 20
    
    def get_queryset(self):
        """支持按用户名搜索和按登录结果筛选"""
        queryset = super().get_queryset()
        search = self.request.GET.get('search', '')
        status = self.request.GET.get('status', '')
        if search:
            queryset = queryset.filter(username__icontains=search)
        if status:
            queryset = queryset.filter(status=status)
        return queryset.order_by('-login_time')


def reset_password(request, pk):
    """重置用户密码 - 将密码重置为默认值 Admin@123"""
    user = get_object_or_404(User, pk=pk)
    new_password = 'Admin@123'
    user.set_password(new_password)
    user.save()
    log_operation(request.user, '重置密码', 'accounts', 'reset_password', '',
                 f"重置用户 {user.username} 的密码")
    messages.success(request, f'用户 {user.username} 密码已重置为: {new_password}')
    return redirect('accounts:user_list')
