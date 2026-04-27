"""审计日志模块 - 视图函数"""

from django.shortcuts import render
from django.views.generic import ListView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from .models import OperationLog


@method_decorator([login_required], name='dispatch')
class OperationLogListView(ListView):
    """操作日志列表视图 - 支持按模块/操作类型/关键字筛选，双轨审计"""
    model = OperationLog
    template_name = 'logs/operation_log.html'
    context_object_name = 'logs'
    paginate_by = 30
    
    def get_queryset(self):
        """支持按模块、操作类型、关键字筛选，预加载用户信息"""
        queryset = super().get_queryset().select_related('user')
        
        # 筛选条件
        module = self.request.GET.get('module', '')
        action = self.request.GET.get('action', '')
        search = self.request.GET.get('search', '')
        
        if module:
            queryset = queryset.filter(module=module)
        if action:
            queryset = queryset.filter(action=action)
        if search:
            queryset = queryset.filter(
                object_type__icontains=search
            ) | queryset.filter(
                new_value__icontains=search
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """将筛选选项和当前筛选条件传递给模板"""
        context = super().get_context_data(**kwargs)
        # 模块选项列表（与各业务模块对应）
        context['modules'] = [
            ('ipam', 'IPAM'),
            ('dns', 'DNS管理'),
            ('devices', '设备管理'),
            ('accounts', '用户管理'),
        ]
        # 操作类型选项列表
        context['actions'] = [
            ('新增', '新增'), ('修改', '修改'), ('删除', '删除'),
            ('导入', '导入'), ('导出', '导出'), ('分配', '分配'),
            ('释放', '释放'), ('标记', '标记'), ('关联', '关联'),
            ('登录', '登录'), ('退出', '退出'),
        ]
        context['current_module'] = self.request.GET.get('module', '')
        context['current_action'] = self.request.GET.get('action', '')
        context['search'] = self.request.GET.get('search', '')
        return context
