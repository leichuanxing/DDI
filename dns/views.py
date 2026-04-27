"""
DNS管理模块 - 视图函数
包含仪表盘、服务管理、配置同步、全局配置、ACL、View、Zone、记录、
转发、主从、日志、发布、备份、审计等全部页面视图

P1阶段: 骨架实现 - 每个视图返回基础可渲染页面
P2-P5阶段: 逐步填充完整业务逻辑
"""

import json
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    DnsServer, DnsGlobalOption, DnsAcl, DnsAclItem,
    DnsView, DnsZone, DnsRecord, DnsForwardRule,
    DnsSyncStatus, DnsPublishVersion, DnsPublishObject,
    DnsBackup, DnsAuditLog,
)
from .forms import (
    DnsServerForm, DnsGlobalOptionForm, DnsAclForm, DnsAclItemFormSet,
    DnsViewForm, DnsZoneForm, DnsRecordForm, DnsForwardRuleForm,
    ZoneSearchForm, RecordSearchForm,
)
from common.logger import log_operation


# ====================================================================
# 辅助函数
# ====================================================================

def _get_server():
    """获取当前管理的DNS服务器实例（优先本地）"""
    return DnsServer.get_local_server()


def _log_dns(user, action, category, object_name='', detail='', old_value='', new_value='', result='success'):
    """DNS模块专用日志记录"""
    try:
        DnsAuditLog.objects.create(
            user=user, action=action, category=category,
            object_name=object_name, detail=detail,
            old_value=old_value[:2000], new_value=new_value[:2000],
            result=result
        )
    except Exception:
        pass


# ====================================================================
# 1. DNS仪表盘
# ====================================================================
@method_decorator([login_required], name='dispatch')
class DashboardView(ListView):
    """DNS管理仪表盘 - 展示全局状态统计和摘要信息"""
    template_name = 'dns/dashboard.html'
    context_object_name = None

    def get_queryset(self):
        return None  # 不需要标准列表查询

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        server = _get_server()

        # 核心统计
        context.update({
            'stats': {
                'server_hostname': server.hostname,
                'zone_total': DnsZone.objects.count(),
                'zone_master': DnsZone.objects.filter(zone_type='master').count(),
                'zone_slave': DnsZone.objects.filter(zone_type='slave').count(),
                'zone_forward': DnsZone.objects.filter(zone_type='forward').count(),
                'zone_enabled': DnsZone.objects.filter(enabled=True).count(),
                'view_count': DnsView.objects.count(),
                'acl_count': DnsAcl.objects.count(),
                'record_total': DnsRecord.objects.filter(enabled=True).count(),
                'forward_rule_count': DnsForwardRule.objects.filter(enabled=True).count(),
            },
            'recent_publishes': DnsPublishVersion.objects.all()[:5],
            'recent_audits': DnsAuditLog.objects.select_related('user')[:10],
            'alerts': [],  # P2阶段填充告警逻辑
        })
        return context


# ====================================================================
# 2. DNS服务管理
# ====================================================================
@login_required
def service_manage(request):
    """DNS服务管理页面 - 查看状态、执行启停操作"""
    from .services.bind9_service import Bind9Service
    server = _get_server()
    svc = Bind9Service(server)

    # 获取真实状态信息
    service_info = svc.get_service_status()

    # 将检测到的BIND版本回写到数据库（避免每次显示"检测中..."）
    detected_ver = service_info.get('bind_version', '')
    if detected_ver and not server.bind_version:
        server.bind_version = detected_ver
        server.save(update_fields=['bind_version'])

    rndc_info = None

    context = {
        'server': server,
        'service_info': service_info,
        'rndc_info': rndc_info,
        'recent_operations': DnsAuditLog.objects.filter(category__in=['service']).select_related('user')[:10],
    }
    return render(request, 'dns/service.html', context)


@login_required
def api_service_action(request):
    """API/表单: 执行服务操作（start/stop/restart/reload/reconfig/flush/status）
    
    支持两种调用方式:
    - AJAX fetch (X-Requested-With: XMLHttpRequest) → 返回 JSON
    - 表单 POST (普通提交)                  → 执行后重定向回服务页面
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持POST'})
    action = request.POST.get('action', '')
    allowed_actions = ['start', 'stop', 'restart', 'reload', 'reconfig', 'flush_cache', 'status']
    if action not in allowed_actions:
        return JsonResponse({'success': False, 'error': f'不支持的操作: {action}'})

    from .services.bind9_service import Bind9Service
    svc = Bind9Service()

    action_map = {
        'start': ('service_start', f'启动named服务'),
        'stop': ('service_stop', f'停止named服务'),
        'restart': ('service_restart', f'重启named服务'),
        'reload': ('service_reload', f'Reload配置'),
        'reconfig': ('service_reconfig', f'Reconfig加载新区域'),
        'flush_cache': ('flush_cache', f'DNS缓存清理'),
        'status': ('rndc_status', f'获取rndc状态'),
    }

    method_name, label = action_map.get(action, (None, ''))
    result = {'success': False, 'message': ''}

    if method_name and hasattr(svc, method_name):
        try:
            method = getattr(svc, method_name)
            if action == 'flush_cache':
                ret = method()
            elif action == 'status':
                ret = method()
                result['rndc_output'] = ret.get('output', '')
                result['rndc_parsed'] = ret.get('parsed', {})
            else:
                ret = method()
            result['success'] = ret.get('success', True)
            result['message'] = ret.get('output', f'{label} 已提交')
            _log_dns(request.user, f'service_{action}', 'service', action,
                     detail=result['message'][:500],
                     result='success' if result['success'] else 'failed')
        except Exception as e:
            result['message'] = f'{label} 执行异常: {str(e)}'
            _log_dns(request.user, f'service_{action}', 'service', action,
                     detail=result['message'], result='failed')
    else:
        result['message'] = f'未知操作: {action}'

    # AJAX请求返回JSON，表单POST则重定向回服务页面
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse(result)
    else:
        # 表单提交：通过messages框架传递结果，然后重定向
        from django.contrib import messages
        if result['success']:
            messages.success(request, f'{label}: {result["message"][:100]}')
        else:
            messages.error(request, f'{label} 失败: {result["message"][:100]}')
        from django.shortcuts import redirect
        return redirect('dns:service')


# ====================================================================
# 3. 配置同步
# ====================================================================

def _parse_named_conf(config_path='/etc/named.conf'):
    """解析磁盘上的named.conf，提取acl/view/zone/forwarders等配置对象

    Returns:
        dict: {
            'zones': list of {'name','type','file'},
            'acls': list of {'name','items'},
            'views': list of {'name'},
            'options_keys': set,
            'raw_content': str,
            'error': str or None,
        }
    """
    result = {
        'zones': [], 'acls': [], 'views': [],
        'options_keys': set(), 'forwarders': [],
        'include_files': [], 'raw_content': '',
        'error': None,
    }
    try:
        with open(config_path, 'r') as f:
            content = f.read()
        result['raw_content'] = content
        lines = content.split('\n')
        i = 0
        depth_stack = []  # track brace nesting
        current_block_type = None

        while i < len(lines):
            line = lines[i].strip()
            # Skip comments and empty lines
            if not line or line.startswith('//') or line.startswith('/*') or line.startswith('#'):
                i += 1
                continue

            # Detect block starts
            acl_match = re.match(r'acl\s+"([^"]+)"\s*\{', line)
            zone_match = re.match(r'zone\s+"([^"]+)"\s*(?:IN\s+)?(?:class\s+\S+\s+)?\{', line)
            view_match = re.match(r'view\s+"([^"]+)"\s*\{', line)
            options_match = re.match(r'options\s*\{', line)

            if acl_match:
                result['acls'].append({'name': acl_match.group(1), 'items': []})
                current_block_type = ('acl', len(result['acls']) - 1)
                depth_stack.append(('acl',))
            elif zone_match:
                ztype_val = ''
                for j in range(i+1, min(i+10, len(lines))):
                    tl = lines[j].strip()
                    tmatch = re.match(r'type\s+(master|slave|forward|stub)\s*;', tl)
                    if tmatch:
                        ztype_val = tmatch.group(1); break
                result['zones'].append({'name': zone_match.group(1), 'type': ztype_val or 'unknown'})
                depth_stack.append(('zone',))
            elif view_match:
                result['views'].append({'name': view_match.group(1)})
                depth_stack.append(('view',))
            elif options_match:
                depth_stack.append(('options',))

            # Track closing braces
            open_count = line.count('{')
            close_count = line.count('}')
            for _ in range(open_count):
                pass  # already handled above
            for _ in range(close_count):
                if depth_stack:
                    depth_stack.pop()

            # Extract include directives
            inc_match = re.match(r'include\s+"([^"]+)"\s*;', line)
            if inc_match:
                result['include_files'].append(inc_match.group(1))

            # Extract forwarders from options (simple heuristic)
            fwd_match = re.match(r'forwarders\s*\{', line)
            if fwd_match:
                for j in range(i+1, min(i+20, len(lines))):
                    ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[0-9a-fA-F:]+)', lines[j])
                    if ip_match and ';' not in lines[j][:lines[j].find(ip_match.group(1)) + 5]:
                        result['forwarders'].append(ip_match.group(1))
                    elif '};' in lines[j]:
                        break

            i += 1

    except FileNotFoundError:
        result['error'] = f'配置文件不存在: {config_path}'
    except PermissionError:
        result['error'] = f'无权限读取: {config_path}'
    except Exception as e:
        result['error'] = f'解析异常: {str(e)}'

    return result


@login_required
def config_sync_view(request):
    """配置同步页面 - 从磁盘读取named.conf并对比数据库差异"""
    server = _get_server()

    # 解析磁盘上的named.conf
    disk_data = _parse_named_conf(server.named_conf_path)

    # 数据库中的对象
    db_zones = list(DnsZone.objects.values_list('name', flat=True))
    db_acls = list(DnsAcl.objects.values_list('name', flat=True))
    db_views = list(DnsView.objects.values_list('name', flat=True))

    # 差异分析
    diff_items = []
    disk_zone_names = [z['name'] for z in disk_data.get('zones', [])]
    disk_acl_names = [a['name'] for a in disk_data.get('acls', [])]
    disk_view_names = [v['name'] for v in disk_data.get('views', [])]

    # Zone差异
    only_disk_zones = set(disk_zone_names) - set(db_zones)
    only_db_zones = set(db_zones) - set(disk_zone_names)
    common_zones = set(disk_zone_names) & set(db_zones)
    if only_disk_zones:
        diff_items.append(f"[+] 磁盘多出Zone ({len(only_disk_zones)}): {', '.join(sorted(only_disk_zones)[:5])}{'...' if len(only_disk_zones) > 5 else ''}")
    if only_db_zones:
        diff_items.append(f"[-] 数据库多出Zone ({len(only_db_zones)}): {', '.join(sorted(only_db_zones)[:5])}{'...' if len(only_db_zones) > 5 else ''}")

    # ACL差异
    only_disk_acls = set(disk_acl_names) - set(db_acls)
    only_db_acls = set(db_acls) - set(disk_acl_names)
    if only_disk_acls:
        diff_items.append(f"[+] 磁盘多出ACL ({len(only_disk_acls)}): {', '.join(sorted(only_disk_acls))}")
    if only_db_acls:
        diff_items.append(f"[-] 数据库多出ACL ({len(only_db_acls)}): {', '.join(sorted(only_db_acls))}")

    # View差异
    only_disk_views = set(disk_view_names) - set(db_views)
    only_db_views = set(db_views) - set(disk_view_names)
    if only_disk_views:
        diff_items.append(f"[+] 磁盘多出View: {', '.join(sorted(only_disk_views))}")
    if only_db_views:
        diff_items.append(f"[-] 数据库多出View: {', '.join(sorted(only_db_views))}")

    context = {
        'server': server,
        'disk_data': disk_data,
        'db_objects': {
            'zones': db_zones,
            'acls': db_acls,
            'views': db_views,
            'zone_total': len(db_zones),
            'acl_total': len(db_acls),
            'view_total': len(db_views),
        },
        'diff_result': '\n'.join(diff_items) if diff_items else None,
        'sync_stats': {
            'disk_zone_count': len(disk_zone_names),
            'disk_acl_count': len(disk_acl_names),
            'disk_view_count': len(disk_view_names),
            'db_zone_count': len(db_zones),
            'db_acl_count': len(db_acls),
            'db_view_count': len(db_views),
            'diff_count': len(only_disk_zones) + len(only_db_zones) + len(only_disk_acls) + len(only_db_acls) + len(only_disk_views) + len(only_db_views),
        },
    }
    return render(request, 'dns/config_sync.html', context)


@login_required
def api_sync_execute(request):
    """API: 执行磁盘到数据库的配置同步"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持POST'})

    server = _get_server()
    disk_data = _parse_named_conf(server.named_conf_path)

    if disk_data.get('error'):
        return JsonResponse({'success': False, 'error': disk_data['error']})

    created_count = 0
    errors = []

    # 同步Zone
    existing_zones = set(DnsZone.objects.values_list('name', flat=True))
    for z in disk_data.get('zones', []):
        if z['name'] not in existing_zones:
            try:
                direction = 'reverse' if 'in-addr.arpa' in z['name'] or 'ip6.arpa' in z['name'] else 'forward'
                DnsZone.objects.create(
                    name=z['name'],
                    zone_type=z.get('type', 'master'),
                    direction_type=direction,
                    enabled=True,
                    description='从磁盘配置自动导入',
                )
                created_count += 1
            except Exception as e:
                errors.append(str(e))

    # 同步ACL
    existing_acls = set(DnsAcl.objects.values_list('name', flat=True))
    for a in disk_data.get('acls', []):
        if a['name'] not in existing_acls and a['name'] not in ('any', 'none', 'localhost', 'localnets'):
            try:
                DnsAcl.objects.create(name=a['name'], description='从磁盘配置自动导入')
                created_count += 1
            except Exception as e:
                errors.append(str(e))

    _log_dns(request.user, 'config_sync', 'sync', '配置同步',
             detail=f'解析到{len(disk_data["zones"])}个Zone/{len(disk_data["acls"])}个ACL, 新建{created_count}条')
    return JsonResponse({
        'success': True,
        'message': f'同步完成！新建 {created_count} 个对象（{len(disk_data["zones"])} zones, {len(disk_data["acls"])} acls）',
        'created': created_count,
        'errors': errors[:5],
    })


# ====================================================================
# 4. 全局配置
# ====================================================================
@method_decorator([login_required], name='dispatch')
class GlobalOptionEdit(UpdateView):
    """全局配置编辑页 - 保存后可选择仅存草稿或立即应用到BIND9"""
    model = DnsGlobalOption
    form_class = DnsGlobalOptionForm
    template_name = 'dns/options.html'

    def get_object(self, queryset=None):
        server = _get_server()
        obj, created = DnsGlobalOption.objects.get_or_create(server=server)
        return obj

    def form_valid(self, form):
        """表单验证通过后，根据提交方式决定是否立即应用到named.conf"""
        self.object = form.save()
        action_type = self.request.POST.get('submit_action', 'draft')

        if action_type == 'apply':
            # ====== 立即应用到 BIND9 ======
            from .services.config_renderer import ConfigRenderer
            from .services.bind9_service import Bind9Service
            server = _get_server()
            config_path = server.named_conf_path

            try:
                # 1) 渲染配置
                renderer = ConfigRenderer(server)
                config_text = renderer.render_full_config()

                # 2) 写入文件（先备份原文件）
                import shutil as _shutil
                backup_path = config_path + '.bak'
                if __import__('os').path.exists(config_path):
                    _shutil.copy2(config_path, backup_path)

                with open(config_path, 'w') as f:
                    f.write(config_text)

                # 3) 验证语法
                svc = Bind9Service(server)
                check_result = svc.check_conf()

                if check_result.get('passed'):
                    # 4) 语法通过 → reload/restart
                    svc.service_reload()
                    messages.success(
                        self.request,
                        f'配置已应用并重载BIND9成功 | {check_result.get("output", "")[:100]}'
                    )
                    _log_dns(self.request.user, 'apply_global_option', 'global',
                             '全局配置已应用', result='success')
                else:
                    # 恢复备份
                    if __import__('os').path.exists(backup_path):
                        _shutil.copy2(backup_path, config_path)
                    messages.error(
                        self.request,
                        f'配置语法校验失败，已回滚原配置: {check_result.get("output", "")[:200]}'
                    )
                    _log_dns(self.request.user, 'apply_global_option', 'global',
                             f'配置语法错误已回滚: {check_result.get("output","")[:200]}',
                             result='failed')
            except Exception as e:
                messages.error(self.request, f'应用配置异常: {e}')
                _log_dns(self.request.user, 'apply_global_option', 'global',
                         f'应用异常: {e}', result='failed')
        else:
            # 仅保存为草稿
            messages.success(self.request, '全局配置已保存为草稿（未生效）')

        _log_dns(self.request.user, 'update_global_option', 'global', '全局配置')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('dns:options')


@login_required
def global_option_preview(request):
    """预览生成的named.conf配置文本"""
    from .services.config_renderer import ConfigRenderer
    server = _get_server()
    try:
        option = DnsGlobalOption.objects.get(server=server)
    except DnsGlobalOption.DoesNotExist:
        option = None

    config_text = ''
    if request.method == 'POST' or request.GET.get('preview') == '1':
        try:
            renderer = ConfigRenderer(server)
            config_text = renderer.render_full_config()
        except Exception as e:
            config_text = f'配置渲染错误: {e}'

    context = {'option': option, 'config_text': config_text}
    return render(request, 'dns/options.html', context)


# ====================================================================
# 5. ACL管理
# ====================================================================
@method_decorator([login_required], name='dispatch')
class AclListView(ListView):
    """ACL列表"""
    model = DnsAcl
    template_name = 'dns/acl_list.html'
    context_object_name = 'acls'
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = {}
        return context

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('items')
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return queryset


@login_required
def acl_detail(request, pk):
    """ACL详情 + 条目编辑"""
    acl = get_object_or_404(DnsAcl, pk=pk)

    # POST 处理
    if request.method == 'POST':
        if 'save_info' in request.POST:
            form = DnsAclForm(request.POST, instance=acl)
            if form.is_valid():
                form.save()
                messages.success(request, f'ACL "{acl.name}" 基本信息已保存')
                log_operation(request.user, '编辑', 'dns', 'acl', '', acl.name)
                _log_dns(request.user, 'update_acl', 'acl', acl.name)
                return redirect('dns:acl_detail', pk=acl.pk)
        elif 'save_items' in request.POST:
            # 更新现有条目
            items = acl.items.all()
            for item in items:
                type_key = f'item_type_{item.id}'
                value_key = f'item_value_{item.id}'
                order_key = f'item_order_{item.id}'
                if type_key in request.POST:
                    item.item_type = request.POST[type_key]
                    item.value = request.POST.get(value_key, '')
                    item.order_index = int(request.POST.get(order_key, 0) or 0)
                    item.save()
            # 创建新条目 — 遍历所有 new_item_type_* 字段
            for type_key in sorted(request.POST.keys()):
                if not type_key.startswith('new_item_type_'):
                    continue
                idx = type_key.replace('new_item_type_', '')
                value_key = f'new_item_value_{idx}'
                order_key = f'new_item_order_{idx}'
                new_type = request.POST[type_key]
                new_value = request.POST.get(value_key, '').strip()
                new_order = int(request.POST.get(order_key, 0) or 0)
                if new_type and (new_value or new_type in ('any', 'none', 'localhost', 'localnets')):
                    DnsAclItem.objects.create(
                        acl=acl,
                        item_type=new_type,
                        value=new_value,
                        order_index=new_order,
                    )
            messages.success(request, f'ACL "{acl.name}" 条目已保存')
            log_operation(request.user, '编辑', 'dns', 'acl_item', '', acl.name)
            _log_dns(request.user, 'update_acl_items', 'acl', acl.name)
            return redirect('dns:acl_detail', pk=acl.pk)

    # GET 或 POST 失败后重新渲染
    form = DnsAclForm(instance=acl)
    items = acl.items.all()
    context = {
        'acl': acl,
        'form': form,
        'items': items,
        'can_delete': acl.can_delete(),
        # 引用关系
        'used_in_views_clients': acl.used_in_view_clients.all(),
        'used_in_views_dests': acl.used_in_view_dests.all(),
        'used_in_zones_transfer': DnsZone.objects.filter(allow_transfer_acl=acl),
        'used_in_zones_update': DnsZone.objects.filter(allow_update_acl=acl),
    }
    return render(request, 'dns/acl_form.html', context)


@method_decorator([login_required], name='dispatch')
class AclCreateView(CreateView):
    model = DnsAcl
    form_class = DnsAclForm
    template_name = 'dns/acl_form.html'
    success_url = reverse_lazy('dns:acl_list')

    def form_valid(self, form):
        messages.success(self.request, f'ACL "{form.instance.name}" 创建成功')
        log_operation(self.request.user, '新增', 'dns', 'acl', '', form.instance.name)
        _log_dns(self.request.user, 'create_acl', 'acl', form.instance.name)
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class AclUpdateView(UpdateView):
    model = DnsAcl
    form_class = DnsAclForm
    template_name = 'dns/acl_form.html'
    success_url = reverse_lazy('dns:acl_list')


@method_decorator([login_required], name='dispatch')
class AclDeleteView(DeleteView):
    model = DnsAcl
    template_name = 'dns/acl_form.html'
    success_url = reverse_lazy('dns:acl_list')

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        if not obj.can_delete():
            messages.error(request, f'ACL "{obj.name}" 被引用或为内置ACL，无法删除')
            return redirect(obj.get_absolute_url())
        messages.success(request, f'ACL "{obj.name}" 已删除')
        log_operation(request.user, '删除', 'dns', 'acl', obj.name, '')
        _log_dns(request.user, 'delete_acl', 'acl', obj.name)
        return super().delete(request, *args, **kwargs)


# ====================================================================
# 6. View管理
# ====================================================================
@method_decorator([login_required], name='dispatch')
class ViewListView(ListView):
    model = DnsView
    template_name = 'dns/view_list.html'
    context_object_name = 'views'


@method_decorator([login_required], name='dispatch')
class ViewCreateView(CreateView):
    model = DnsView
    form_class = DnsViewForm
    template_name = 'dns/view_form.html'
    success_url = reverse_lazy('dns:view_list')

    def form_valid(self, form):
        messages.success(self.request, f'View "{form.instance.name}" 创建成功')
        _log_dns(self.request.user, 'create_view', 'view', form.instance.name)
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class ViewUpdateView(UpdateView):
    model = DnsView
    form_class = DnsViewForm
    template_name = 'dns/view_form.html'
    success_url = reverse_lazy('dns:view_list')


@method_decorator([login_required], name='dispatch')
class ViewDeleteView(DeleteView):
    model = DnsView
    template_name = 'dns/view_form.html'
    success_url = reverse_lazy('dns:view_list')

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        messages.success(request, f'View "{obj.name}" 已删除')
        _log_dns(request.user, 'delete_view', 'view', obj.name)
        return super().delete(request, *args, **kwargs)


@login_required
def view_preview(request, pk):
    """预览View配置文本"""
    view = get_object_or_404(DnsView.objects.prefetch_related('zones', 'match_clients', 'match_destinations'), pk=pk)
    from .services.config_renderer import ConfigRenderer

    config_text = ''
    try:
        renderer = ConfigRenderer()
        # 渲染该View的zone块
        config_text = renderer.render_view_blocks()
        # 提取仅当前view的块（简单过滤）
        lines = []
        in_target_view = False
        for line in (config_text or '').split('\n'):
            if f'view "{view.name}"' in line:
                in_target_view = True
            if in_target_view:
                lines.append(line)
            if in_target_view and line.strip() == '};':
                break
        config_text = '\n'.join(lines) if lines else '// 该View下暂无内容或渲染异常'
    except Exception as e:
        config_text = f'View配置渲染失败: {e}'

    context = {'view': view, 'config_text': config_text}
    return render(request, 'dns/view_form.html', context)


# ====================================================================
# 7. 区域管理 (核心)
# ====================================================================
@method_decorator([login_required], name='dispatch')
class ZoneListView(ListView):
    model = DnsZone
    template_name = 'dns/zone_list.html'
    context_object_name = 'zones'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().select_related('view').annotate(
            record_cnt=Count('records', filter=Q(records__enabled=True))
        )
        
        # 筛选
        form = ZoneSearchForm(self.request.GET)
        if form.is_valid() and form.cleaned_data.get('search'):
            queryset = queryset.filter(name__icontains=form.cleaned_data['search'])
        if form.is_valid() and form.cleaned_data.get('zone_type'):
            queryset = queryset.filter(zone_type=form.cleaned_data['zone_type'])
        if form.is_valid() and form.cleaned_data.get('direction_type'):
            queryset = queryset.filter(direction_type=form.cleaned_data['direction_type'])
        if form.is_valid() and form.cleaned_data.get('enabled') == '1':
            queryset = queryset.filter(enabled=True)
        elif form.is_valid() and form.cleaned_data.get('enabled') == '0':
            queryset = queryset.filter(enabled=False)
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = ZoneSearchForm(self.request.GET)
        return context


@login_required
def zone_detail(request, pk):
    """Zone详情页 - SOA信息 + 记录列表"""
    zone = get_object_or_404(DnsZone.objects.select_related('view'), pk=pk)
    records = zone.records.filter(enabled=True).order_by('record_type', 'name')
    
    context = {
        'zone': zone,
        'records': records,
        'soa_record': zone.get_soa_record(),
        'record_count': records.count(),
        'ns_count': records.filter(record_type='NS').count(),
        'other_count': records.count() - records.filter(record_type='NS').count(),
    }
    return render(request, 'dns/zone_detail.html', context)


def _ensure_zone_has_soa_ns(zone):
    """为Zone自动生成默认的SOA、NS和NS的A胶水记录（如果不存在）

    新建Zone时必须至少有:
    - 1条SOA记录
    - 1条NS记录
    - NS主机名对应的A记录（glue record），否则BIND9拒绝加载zone
    """
    import socket as _socket
    from .models import DnsRecord

    origin = zone.name.rstrip('.') + '.'
    ns_host = zone.primary_ns or ('ns.' + origin)
    admin = zone.admin_mail or ('admin.' + origin)

    # ---- SOA 记录 ----
    if not zone.records.filter(record_type='SOA').exists():
        serial = zone.serial_no or 1
        soa_value = (
            f'{ns_host} {admin} {serial} '
            f'{zone.refresh or 3600} {zone.retry or 600} '
            f'{zone.expire or 86400} {zone.minimum or 3600}'
        )
        DnsRecord.objects.create(
            zone=zone, name='@', record_type='SOA',
            value=soa_value, ttl=zone.default_ttl or 3600, enabled=True,
        )

    # ---- NS 记录 ----
    if not zone.records.filter(record_type='NS', enabled=True).exists():
        DnsRecord.objects.create(
            zone=zone, name='@', record_type='NS',
            value=ns_host, ttl=zone.default_ttl or 3600, enabled=True,
        )

    # ---- NS 对应的 A 胶水记录 (glue) ----
    # 提取NS主机名(如 ns.devnets.net -> ns)，检查是否有对应A记录
    ns_short = ns_host.rstrip('.').replace(origin, '').rstrip('.') or '@'
    if not zone.records.filter(record_type='A', name=ns_short, enabled=True).exists():
        # 尝试获取本机IP作为NS地址
        try:
            # 优先获取非loopback的真实IP
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            host_ip = s.getsockname()[0]
            s.close()
        except Exception:
            host_ip = '127.0.0.1'
        DnsRecord.objects.create(
            zone=zone, name=ns_short, record_type='A',
            value=host_ip, ttl=zone.default_ttl or 3600, enabled=True,
        )


def _apply_zone_config_change(request):
    """Zone变更后统一同步: 重新渲染named.conf + 更新zone文件 + 重载BIND9

    所有 Zone 的 create/update/delete 操作后均调用此函数，
    确保数据库变更立即同步到 BIND9 运行配置。
    """
    from .services.config_renderer import ConfigRenderer
    from .services.bind9_service import Bind9Service
    import shutil as _shutil, os as _os, traceback as _tb

    server = _get_server()
    try:
        renderer = ConfigRenderer(server)
        config_text = renderer.render_full_config()

        # 1) 备份并写入 named.conf
        backup_path = server.named_conf_path + '.bak'
        if _os.path.exists(server.named_conf_path):
            _shutil.copy2(server.named_conf_path, backup_path)
        with open(server.named_conf_path, 'w') as f:
            f.write(config_text)

        # 2) 生成/更新所有zone文件
        for zone in DnsZone.objects.filter(enabled=True):
            try:
                zone_text = renderer.render_zone_file(zone)
                fname = zone.file_name or zone.generate_filename()
                fpath = _os.path.join('/var/named', fname)
                with open(fpath, 'w') as zf:
                    zf.write(zone_text)
            except Exception as zone_err:
                logger = __import__('logging').getLogger('dns.zone_sync')
                logger.warning(f'生成zone文件失败 [{zone.name}]: {zone_err}')

        # 3) 验证语法并重载
        svc = Bind9Service(server)
        check_result = svc.check_conf()
        if check_result.get('passed'):
            reload_result = svc.service_reload()
            messages.success(
                request,
                f'配置已自动应用并重载 | checkconf: {check_result.get("output", "")[:80]} | reload: {reload_result.get("output", "")[:80]}'
            )
            _log_dns(request.user, 'apply_zone_config', 'system',
                     'Zone变更后自动应用', result='success')
        else:
            # 校验失败 → 回滚named.conf
            if _os.path.exists(backup_path):
                _shutil.copy2(backup_path, server.named_conf_path)
            error_detail = check_result.get("output", "未知错误")[:300]
            messages.error(request,
                           f'配置校验失败已回滚: {error_detail}')
            _log_dns(request.user, 'apply_zone_config', 'system',
                     f'配置回滚: {error_detail}', result='failed')
    except Exception as e:
        detail = f'{e}\n{_tb.format_exc()}'
        messages.error(request, f'自动应用配置异常: {e}')
        _log_dns(request.user, 'apply_zone_config', 'system',
                 f'异常:{detail}', result='failed')


@method_decorator([login_required], name='dispatch')
class ZoneCreateView(CreateView):
    model = DnsZone
    form_class = DnsZoneForm
    template_name = 'dns/zone_form.html'

    def get_success_url(self):
        messages.success(self.request, f'区域 "{self.object.name}" 创建成功')
        _log_dns(self.request.user, 'create_zone', 'zone', self.object.name)
        return reverse('dns:zone_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.instance.file_name:
            form.instance.file_name = form.instance.generate_filename()
            form.instance.save(update_fields=['file_name'])

        # 自动为新建Zone生成默认的SOA + NS记录（如果尚不存在）
        _ensure_zone_has_soa_ns(form.instance)

        # 创建后自动同步配置
        _apply_zone_config_change(self.request)
        return response


@method_decorator([login_required], name='dispatch')
class ZoneUpdateView(UpdateView):
    model = DnsZone
    form_class = DnsZoneForm
    template_name = 'dns/zone_form.html'

    def get_success_url(self):
        messages.success(self.request, f'区域 "{self.object.name}" 更新成功')
        _log_dns(self.request.user, 'update_zone', 'zone', self.object.name)
        return reverse('dns:zone_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        # 更新后自动同步配置
        _apply_zone_config_change(self.request)
        return response


@method_decorator([login_required], name='dispatch')
class ZoneDeleteView(DeleteView):
    model = DnsZone
    template_name = 'dns/zone_confirm_delete.html'
    success_url = reverse_lazy('dns:zone_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = self.object
        ctx['record_count'] = getattr(obj, 'record_count', 0) or 0
        if not ctx['record_count']:
            try:
                ctx['record_count'] = obj.records.count()
            except Exception:
                pass
        return ctx

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        zone_name = obj.name
        record_count = getattr(obj, 'record_count', 0) or 0
        try:
            record_count = obj.records.count()
        except Exception:
            pass
        # 先执行删除
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'区域 "{zone_name}" 及其 {record_count} 条记录已被删除')
        log_operation(request.user, '删除', 'dns', 'zone', zone_name, str(record_count) + '条记录')
        _log_dns(request.user, 'delete_zone', 'zone', zone_name, detail=f'删除{record_count}条记录')

        # 删除后自动同步配置
        _apply_zone_config_change(request)

        return response


@login_required
def zone_check(request, pk):
    """校验Zone配置"""
    zone = get_object_or_404(DnsZone.objects.select_related('view'), pk=pk)
    from .services.bind9_service import Bind9Service
    from .services.config_renderer import ConfigRenderer

    check_result = {'passed': True, 'output': '配置校验通过'}
    try:
        renderer = ConfigRenderer()
        zone_text = renderer.render_zone_file(zone)

        svc = Bind9Service()
        result = svc.check_zone(zone.name, zone_content=zone_text)
        check_result = {
            'passed': result.get('passed', False),
            'output': result.get('output', ''),
            'error': result.get('error'),
        }
    except Exception as e:
        check_result = {'passed': False, 'output': f'校验异常: {e}'}

    context = {
        'zone': zone,
        'check_result': check_result,
        'records': zone.records.filter(enabled=True).order_by('record_type', 'name'),
        'record_count': zone.records.filter(enabled=True).count(),
        'ns_count': zone.records.filter(enabled=True, record_type='NS').count(),
        'other_count': zone.records.filter(enabled=True).count()
                     - zone.records.filter(enabled=True, record_type='NS').count(),
    }
    return render(request, 'dns/zone_detail.html', context)


@login_required
def zone_reload(request, pk):
    """reload单个Zone"""
    zone = get_object_or_404(DnsZone, pk=pk)
    _log_dns(request.user, 'reload_zone', 'service', zone.name, result='pending')
    messages.success(request, f'Zone "{zone.name}" reload 指令已发送')
    return redirect('dns:zone_detail', pk=pk)


@login_required
def zone_preview_config(request, pk):
    """预览Zone文件内容"""
    zone = get_object_or_404(DnsZone.objects.select_related('view').prefetch_related('records'), pk=pk)
    from .services.config_renderer import ConfigRenderer

    zone_text = ''
    try:
        renderer = ConfigRenderer()
        zone_text = renderer.render_zone_file(zone)
    except Exception as e:
        zone_text = f'渲染失败: {e}'

    context = {'zone': zone, 'zone_text': zone_text}
    return render(request, 'dns/zone_form.html', context)


# ====================================================================
# 8. 资源记录管理 (核心)
# ====================================================================
@method_decorator([login_required], name='dispatch')
class RecordListView(ListView):
    model = DnsRecord
    template_name = 'dns/record_list.html'
    context_object_name = 'records'
    paginate_by = 25

    def get_queryset(self):
        zone_pk = self.kwargs.get('zone_pk') or self.request.GET.get('zone')
        queryset = DnsRecord.objects.select_related('zone')
        if zone_pk:
            queryset = queryset.filter(zone_id=zone_pk)
        
        # 筛选
        form = RecordSearchForm(self.request.GET)
        if form.is_valid() and form.cleaned_data.get('search'):
            q = Q(name__icontains=form.cleaned_data['search']) | Q(value__icontains=form.cleaned_data['search'])
            queryset = queryset.filter(q)
        if form.is_valid() and form.cleaned_data.get('record_type'):
            queryset = queryset.filter(record_type=form.cleaned_data['record_type'])
        if form.is_valid() and form.cleaned_data.get('enabled') == '1':
            queryset = queryset.filter(enabled=True)
        elif form.is_valid() and form.cleaned_data.get('enabled') == '0':
            queryset = queryset.filter(enabled=False)
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = RecordSearchForm(self.request.GET)
        context['all_zones'] = DnsZone.objects.filter(enabled=True)
        return context


@method_decorator([login_required], name='dispatch')
class RecordCreateView(CreateView):
    model = DnsRecord
    form_class = DnsRecordForm
    template_name = 'dns/record_form.html'

    def _get_zone_from_request(self):
        """从请求参数获取并返回 DnsZone 实例"""
        zone_pk = self.request.GET.get('zone') or self.request.POST.get('zone')
        if not zone_pk:
            return None
        try:
            return DnsZone.objects.select_related('view').get(pk=int(zone_pk))
        except (ValueError, DnsZone.DoesNotExist):
            return None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        zone = self._get_zone_from_request()
        if zone:
            # 有预选区域: 显示区域信息
            ctx['zone_name'] = zone.name
            ctx['zone_type'] = zone.get_zone_type_display()
            ctx['zone_ttl'] = zone.default_ttl or 3600
            ctx['has_zone_selected'] = True
            ctx['all_zones'] = []
        else:
            # 无预选区域: 提供所有可选区域的下拉列表
            from django import forms
            all_zones = list(DnsZone.objects.filter(enabled=True).order_by('name'))
            ctx['has_zone_selected'] = False
            ctx['all_zones'] = all_zones
            # 动态将 zone 字段改为可见下拉框（仅当无预选时）
            if 'form' in ctx:
                f = ctx['form']
                f.fields['zone'].widget = forms.Select(
                    attrs={'class': 'form-select', 'id': 'zone_select'}
                )
                f.fields['zone'].required = True
                f.fields['zone'].empty_label = '-- 请先选择区域 --'
                f.fields['zone'].queryset = DnsZone.objects.filter(enabled=True).order_by('name')
                # 清空之前的错误
                if 'zone' in f.errors:
                    del f.errors['zone']
        return ctx

    def get(self, request, *args, **kwargs):
        """GET请求: 无zone参数且无可用区域时，提示用户"""
        zone = self._get_zone_from_request()
        if not zone and not DnsZone.objects.filter(enabled=True).exists():
            messages.warning(request, '当前没有可用的区域，请先创建区域后再添加记录')
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """重写 POST：在表单验证前确保 zone 已设为实例"""
        self.object = None  # CreateView 需要
        zone = self._get_zone_from_request()
        if not zone:
            messages.error(request, '请先选择区域')
            return redirect('dns:zone_list')

        # 用带 zone 实例的空模型构造初始 instance
        form_class = self.get_form_class()
        form = form_class(data=request.POST, files=request.FILES,
                          instance=DnsRecord(zone=zone))
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_initial(self):
        initial = super().get_initial()
        zone_pk = self.request.GET.get('zone')
        if zone_pk:
            initial['zone'] = zone_pk
        return initial

    def form_valid(self, form):
        zone = form.instance.zone

        # SOA特殊处理: 每区只能一条SOA
        if form.instance.record_type == 'SOA':
            existing_soa = DnsRecord.objects.filter(zone=zone, record_type='SOA').first()
            if existing_soa:
                existing_soa.delete()

        # CNAME规则在model.clean()中处理

        # 自动递增Serial
        zone.bump_serial()

        response = super().form_valid(form)
        messages.success(self.request, f'{form.instance.record_type} 记录创建成功')
        log_operation(self.request.user, '新增', 'dns', 'record',
                      f'{zone.name}/{form.instance.name}', form.instance.value[:100])
        _log_dns(self.request.user, 'create_record', 'record',
                 f'{zone.name}/{form.instance.record_type}/{form.instance.name}')
        return response

    def get_success_url(self):
        return reverse('dns:record_list') + f'?zone={self.object.zone.pk}'


@method_decorator([login_required], name='dispatch')
class RecordUpdateView(UpdateView):
    model = DnsRecord
    form_class = DnsRecordForm
    template_name = 'dns/record_form.html'

    def form_valid(self, form):
        zone = form.instance.zone
        zone.bump_serial()
        response = super().form_valid(form)
        messages.success(self.request, f'{form.instance.record_type} 记录更新成功')
        _log_dns(self.request.user, 'update_record', 'record',
                 f'{zone.name}/{form.instance.record_type}/{form.instance.name}')
        return response

    def get_success_url(self):
        return reverse('dns:record_list') + f'?zone={self.object.zone.pk}'


@method_decorator([login_required], name='dispatch')
class RecordDeleteView(DeleteView):
    model = DnsRecord
    template_name = 'dns/record_confirm_delete.html'

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        zone = obj.zone
        
        # NS保护: 至少保留一条
        if obj.record_type == 'NS' and zone.records.filter(record_type='NS', enabled=True).count() <= 1:
            messages.error(request, f'{zone.name} 最后一条NS记录不能删除')
            return redirect(obj.get_absolute_url())

        zone.bump_serial()
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'{obj.record_type} 记录已删除')
        _log_dns(self.request.user, 'delete_record', 'record',
                 f'{zone.name}/{obj.record_type}/{obj.name}', old_value=obj.value)
        return response

    def get_success_url(self):
        return reverse('dns:record_list') + f'?zone={self.object.zone.pk}'


@login_required
def record_batch_import(request):
    """批量导入记录"""
    if request.method == 'POST':
        count = 0  # P2: 实现解析逻辑
        messages.success(request, f'批量导入完成，共处理 {count} 条记录')
        _log_dns(request.user, 'batch_import_records', 'record', f'批量导入{count}条')
        return redirect('dns:record_list')
    context = {'zones': DnsZone.objects.filter(enabled=True)}
    return render(request, 'dns/record_list.html', context)


@login_required
def record_batch_export(request):
    """批量导出记录"""
    zone_id = request.GET.get('zone')
    format_type = request.GET.get('format', 'csv')
    records = DnsRecord.objects.all()
    if zone_id:
        records = records.filter(zone_id=zone_id)
    
    # P2: 实现导出CSV/JSON/BIND格式
    _log_dns(request.user, 'batch_export_records', 'record', f'导出{records.count()}条')
    return JsonResponse({'download_url': '#'})


# ====================================================================
# 9. 转发管理
# ====================================================================
@login_required
def forward_list(request):
    """转发规则列表"""
    rules = DnsForwardRule.objects.all().select_related('zone')

    # 从全局配置读取forwarders
    global_forwarders = ''
    try:
        server = _get_server()
        opt = DnsGlobalOption.objects.filter(server=server).first()
        if opt and opt.forwarders:
            global_forwarders = opt.forwarders
    except Exception:
        pass

    context = {
        'rules': rules,
        'global_forwarders': global_forwarders,
        'global_policy': '',
    }
    if global_forwarders:
        try:
            opt = DnsGlobalOption.objects.filter(server=_get_server()).first()
            if opt:
                context['global_policy'] = opt.get_forward_policy_display() or opt.forward_policy
        except Exception:
            pass
    return render(request, 'dns/forward.html', context)


@login_required
def forward_create(request):
    """新建转发规则"""
    if request.method == 'POST':
        form = DnsForwardRuleForm(request.POST)
        if form.is_valid():
            rule = form.save()
            messages.success(request, f'转发规则 "{rule}" 已创建')
            _log_dns(request.user, 'create_forward', 'global', str(rule))
            return redirect('dns:forward_list')
    else:
        form = DnsForwardRuleForm()
    return render(request, 'dns/forward.html', {'form': form})


@login_required
def forward_update(request, pk):
    """编辑转发规则"""
    rule = get_object_or_404(DnsForwardRule, pk=pk)
    if request.method == 'POST':
        form = DnsForwardRuleForm(request.POST, instance=rule)
        if form.is_valid():
            updated = form.save()
            messages.success(request, f'转发规则 "{updated}" 已更新')
            _log_dns(request.user, 'update_forward', 'global', str(updated))
            return redirect('dns:forward_list')
    else:
        form = DnsForwardRuleForm(instance=rule)
    return render(request, 'dns/forward.html', {'form': form, 'edit_rule': rule})


@login_required
def forward_delete(request, pk):
    """删除转发规则"""
    rule = get_object_or_404(DnsForwardRule, pk=pk)
    rule_name = str(rule)
    rule.delete()
    messages.success(request, f'转发规则 "{rule_name}" 已删除')
    _log_dns(request.user, 'delete_forward', 'global', rule_name)
    return redirect('dns:forward_list')


@login_required
def api_test_forwarder(request):
    """测试上游DNS连通性 - 使用socket或subprocess测试"""
    import socket
    ip = request.POST.get('ip', '').strip()
    port = int(request.POST.get('port', 53))

    if not ip:
        return JsonResponse({'success': False, 'error': 'IP地址不能为空'})

    result = {'success': True, 'ip': ip, 'port': port}
    try:
        # TCP连接测试 (DNS通常监听53端口)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        start_time = __import__('time').time()
        sock.connect((ip, port))
        latency_ms = round((__import__('time').time() - start_time) * 1000, 1)
        sock.close()
        result['latency_ms'] = latency_ms
        result['message'] = f'{ip}:{port} 连通，延迟 {latency_ms}ms'
    except socket.timeout:
        result['success'] = False
        result['error'] = f'{ip}:{port} 连接超时(5s)'
    except ConnectionRefusedError:
        result['success'] = False
        result['error'] = f'{ip}:{port} 连接被拒绝(服务未运行?)'
    except socket.gaierror as e:
        result['success'] = False
        result['error'] = f'{ip} DNS解析失败: {str(e)}'
    except Exception as e:
        result['success'] = False
        result['error'] = str(e)

    return JsonResponse(result)


# ====================================================================
# 10. 主从同步状态
# ====================================================================
@login_required
def sync_status_list(request):
    """主从同步状态列表"""
    zones = DnsZone.objects.filter(zone_type__in=['master', 'slave']).select_related('view')
    sync_statuses = []
    for zone in zones:
        ss, created = DnsSyncStatus.objects.get_or_create(zone=zone)
        # 自动获取local_serial (如果为0则从SOA记录读取)
        if ss.local_serial == 0:
            soa = zone.get_soa_record()
            if soa and soa.value:
                # SOA值格式: ns admin serial refresh retry expire minimum
                parts = soa.value.split()
                if len(parts) >= 3:
                    try:
                        ss.local_serial = int(parts[2])
                        ss.save(update_fields=['local_serial'])
                    except (ValueError, IndexError):
                        pass
        sync_statuses.append(ss)

    # 同步操作审计日志
    sync_logs = DnsAuditLog.objects.filter(
        category='sync'
    ).select_related('user')[:10]

    context = {
        'sync_statuses': sync_statuses,
        'sync_logs': sync_logs,
        'master_count': sum(1 for s in sync_statuses if s.zone.zone_type == 'master'),
        'slave_count': sum(1 for s in sync_statuses if s.zone.zone_type == 'slave'),
        'in_sync_count': sum(1 for s in sync_statuses if s.in_sync is True),
    }
    return render(request, 'dns/sync.html', context)


@login_required
def api_trigger_sync(request):
    """手动触发同步检查 - 更新DnsSyncStatus并返回结果"""
    zone_id = request.POST.get('zone_id')
    zone = get_object_or_404(DnsZone, pk=zone_id)
    ss, _ = DnsSyncStatus.objects.get_or_create(zone=zone)
    now = timezone.now()

    # 尝试通过rndc触发实际同步（如果是Master区域）
    from .services.bind9_service import Bind9Service
    svc = Bind9Service()
    sync_result = ''
    try:
        if zone.zone_type == 'master':
            # Master: 使用 rndc notify 或 freeze/thaw 触发从服务器拉取
            ret = svc.rndc_command(f'freeze {zone.name}')
            svc.rndc_command(f'thaw {zone.name}')
            # 如果配置了also-notify，尝试通知
            if ss.also_notify:
                notify_ips = [ip.strip() for ip in ss.also_notify.split(',') if ip.strip()]
                for nip in notify_ips:
                    svc.rndc_command(f'notify {zone.name} {nip}')
            sync_result = f'已发送freeze/thaw+notify指令'
        else:
            # Slave: 使用 rndc retransfer 强制重新传输
            ret = svc.rndc_command(f'retransfer {zone.name}')
            sync_result = f'已发送retransfer指令, output={ret.get("output","")[:200]}'
    except Exception as e:
        sync_result = f'rndc执行异常: {str(e)}'

    ss.last_sync_time = now
    ss.last_sync_result = 'checking' if 'error' not in str(sync_result).lower() else 'error'
    ss.last_sync_message = sync_result[:500]
    ss.save()

    _log_dns(request.user, 'trigger_sync', 'sync', zone.name,
             detail=f'触发{zone.get_zone_type_display()}同步: {sync_result}',
             result='success' if '异常' not in sync_result else 'failed')
    return JsonResponse({
        'success': True,
        'zone_name': zone.name,
        'local_serial': ss.local_serial,
        'last_sync_time': now.strftime('%m-%d %H:%M:%S') if now else '--',
        'message': sync_result,
    })


# ====================================================================
# 11. 日志中心
# ====================================================================
@login_required
def dns_log_center(request):
    """DNS日志中心 - 基于DnsAuditLog的分类展示"""
    log_type = request.GET.get('type', 'all')
    search = request.GET.get('search', '').strip()
    category_filter = request.GET.get('category', '')
    start_time = request.GET.get('start_time', '')
    end_time = request.GET.get('end_time', '')

    logs_qs = DnsAuditLog.objects.select_related('user').all()

    # 筛选
    if category_filter:
        logs_qs = logs_qs.filter(category=category_filter)
    if search:
        logs_qs = logs_qs.filter(
            Q(object_name__icontains=search) |
            Q(detail__icontains=search) |
            Q(action__icontains=search)
        )
    if start_time:
        try:
            from django.utils.dateparse import parse_datetime
            st = parse_datetime(start_time)
            if st:
                logs_qs = logs_qs.filter(operation_time__gte=st)
        except Exception:
            pass
    if end_time:
        from django.utils.dateparse import parse_datetime
        et = parse_datetime(end_time)
        if et:
            logs_qs = logs_qs.filter(operation_time__lte=et)

    logs_qs = logs_qs.order_by('-operation_time')[:200]

    log_types = [
        ('all', '全部'),
        ('service', '服务操作'),
        ('zone', '区域管理'),
        ('record', '记录管理'),
        ('acl', 'ACL管理'),
        ('view', 'View管理'),
        ('global', '全局配置'),
        ('publish', '发布操作'),
        ('backup', '备份回滚'),
        ('sync', '同步操作'),
        ('forward', '转发管理'),
    ]

    # 统计各分类数量
    category_stats = {}
    for ct, cl in DnsAuditLog.CATEGORY_CHOICES:
        cat_count = DnsAuditLog.objects.filter(category=ct).count()
        if cat_count > 0:
            category_stats[ct] = cat_count

    context = {
        'log_type': log_type,
        'logs': logs_qs,
        'log_types': log_types,
        'category_stats': category_stats,
        'current_category': category_filter,
        'current_search': search,
        'total_count': logs_qs.count() if hasattr(logs_qs, 'count') else len(list(logs_qs)),
    }
    return render(request, 'dns/logs.html', context)


# ====================================================================
# 12. 发布中心
# ====================================================================
@login_required
def publish_list(request):
    """待发布列表 + 发布历史"""
    from .services.publish_service import PublishService

    # 计算待发布变更（草稿状态/最近更新的对象）
    pending = []
    is_first_publish = False  # 是否首次发布（无任何历史记录）

    # 全局配置 — 草稿 或 首次发布时全部列出
    last_publish = DnsPublishVersion.objects.filter(status='success').order_by('-publish_time').first()
    cutoff_time = last_publish.publish_time if last_publish else None

    if cutoff_time:
        draft_opts = DnsGlobalOption.objects.filter(is_draft=True, updated_at__gt=cutoff_time)
    else:
        is_first_publish = True
        draft_opts = DnsGlobalOption.objects.all()

    for opt in draft_opts.select_related('server'):
        pending.append({
            'object_type': 'global_option',
            'object_name': f'全局配置-{opt.server.hostname if opt.server else "默认"}',
            'action': 'create' if is_first_publish else 'update',
            'diff_content': f'options: directory={opt.directory}, forwarders={opt.forwarders[:30] or "未设置"}',
        })

    # Zone 变更 — 有基线时间则增量检测，否则列出所有enabled zone
    if cutoff_time:
        zone_qs = DnsZone.objects.filter(updated_at__gt=cutoff_time)
    else:
        is_first_publish = True
        zone_qs = DnsZone.objects.filter(enabled=True)

    for z in zone_qs.select_related('view'):
        action = 'create' if (is_first_publish or (z.created_at and z.created_at > cutoff_time)) else 'update'
        pending.append({
            'object_type': 'zone',
            'object_name': z.name,
            'action': action,
            'diff_content': (
                f'{z.get_zone_type_display()} / {z.get_direction_type_display()} '
                f'/ enabled={z.enabled} / records={z.record_count}'
            ),
        })

    # ACL 变更
    if cutoff_time:
        acl_qs = DnsAcl.objects.filter(updated_at__gt=cutoff_time)
    else:
        acl_qs = DnsAcl.objects.all()

    for acl in acl_qs:
        pending.append({
            'object_type': 'acl',
            'object_name': acl.name,
            'action': 'create' if is_first_publish else 'update',
            'diff_content': f'ACL {acl.name} ({acl.item_count}条目)',
        })

    # View 变更
    if cutoff_time:
        view_qs = DnsView.objects.filter(updated_at__gt=cutoff_time)
    else:
        view_qs = DnsView.objects.all()

    for view in view_qs:
        pending.append({
            'object_type': 'view',
            'object_name': view.name,
            'action': 'create' if is_first_publish else 'update',
            'diff_content': f'View {view.name} (zones={view.zone_count})',
        })

    versions = DnsPublishVersion.objects.all()[:20]

    context = {
        'pending': pending,
        'pending_count': len(pending),
        'versions': versions,
        'last_publish': last_publish,
        'is_first_publish': is_first_publish,
    }
    return render(request, 'dns/publish.html', context)


@login_required
def publish_detail(request, pk):
    """发布版本详情"""
    version = get_object_or_404(DnsPublishVersion.objects.prefetch_related('publish_objects'), pk=pk)

    # 尝试获取关联备份
    backup = None
    try:
        backup = version.backups.filter(backup_type='pre_publish').first()
    except Exception:
        pass

    context = {
        'version': version,
        'objects': list(version.publish_objects.all()) if hasattr(version, 'publish_objects') else [],
        'backup': backup,
    }
    return render(request, 'dns/publish.html', context)


@login_required
def publish_confirm(request, pk):
    """确认执行发布"""
    version = get_object_or_404(DnsPublishVersion, pk=pk)
    if request.method == 'POST':
        from .services.publish_service import PublishService
        server = _get_server()

        svc = PublishService(user=request.user, notes=request.POST.get('notes', ''))

        # 如果是已有版本，直接走完整发布流程
        if version.status != 'pending':
            messages.error(request, f'v{version.version_number} 状态为 {version.get_status_display}，无法重复发布')
            return redirect('dns:publish_list')

        version.status = 'publishing'
        version.publisher = request.user
        version.save()

        result = svc.execute_publish()

        if result['success']:
            published_ver = result['version']
            messages.success(
                request,
                f'v{published_ver.version_number} 发布成功！'
                f'(校验通过, 备份完成, 配置已reload)'
            )
            _log_dns(request.user, 'publish', 'publish', f'v{published_ver.version_number}',
                     detail=f'发布成功，共{published_ver.object_count}个变更对象')
            return redirect('dns:publish_list')
        else:
            error_msg = '; '.join(result.get('errors', ['未知错误']))
            messages.error(request, f'发布失败: {error_msg}')
            _log_dns(request.user, 'publish_failed', 'publish', f'v{version.version_number}',
                     detail=f'发布失败: {error_msg}', result='failed')
            return redirect('dns:publish_detail', pk=pk)

    context = {'version': version}
    return render(request, 'dns/publish.html', context)


@login_required
def api_quick_publish(request):
    """API: 快速发布（一键发布所有待发布变更）- AJAX调用"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持POST'})

    from .services.publish_service import PublishService
    svc = PublishService(user=request.user, notes='一键快速发布')

    result = svc.execute_publish()

    if result['success']:
        ver = result.get('version')
        _log_dns(request.user, 'quick_publish', 'publish',
                 f'v{ver.version_number}' if ver else 'unknown',
                 detail=f'快速发布成功, {len(result.get("warnings", []))} warnings')
        return JsonResponse({
            'success': True,
            'message': f'发布成功！v{ver.version_number}' if ver else '发布成功！',
            'version_number': ver.version_number if ver else '',
            'warnings': result.get('warnings', []),
        })
    else:
        return JsonResponse({
            'success': False,
            'error': '; '.join(result.get('errors', ['未知错误'])),
            'step': result.get('step', ''),
        })


@login_required
def publish_history(request):
    """发布历史"""
    versions = DnsPublishVersion.objects.select_related('publisher').all()
    context = {'versions': versions}
    return render(request, 'dns/publish.html', context)


# ====================================================================
# 13. 备份回滚
# ====================================================================
@login_required
def backup_list(request):
    """备份版本列表"""
    backups = DnsBackup.objects.select_related('version', 'backup_user', 'version__publisher').all()[:50]

    # 统计
    total_backups = DnsBackup.objects.count()
    auto_backups = DnsBackup.objects.filter(backup_type='pre_publish').count()
    manual_backups = DnsBackup.objects.filter(backup_type='manual').count()

    context = {
        'backups': backups,
        'total_backups': total_backups,
        'auto_backups': auto_backups,
        'manual_backups': manual_backups,
    }
    return render(request, 'dns/backup.html', context)


@login_required
def backup_detail(request, pk):
    """备份详情 - 显示配置内容预览"""
    backup = get_object_or_404(
        DnsBackup.objects.select_related('version', 'backup_user'), pk=pk
    )
    context = {'backup': backup}
    return render(request, 'dns/backup.html', context)


@login_required
def confirm_rollback(request, pk):
    """确认回滚到指定备份版本"""
    backup = get_object_or_404(
        DnsBackup.objects.select_related('version', 'version__publisher', 'backup_user'), pk=pk
    )

    if request.method == 'POST':
        from .services.publish_service import RollbackService

        svc = RollbackService(user=request.user)
        result = svc.execute_rollback(pk)

        if result['success']:
            messages.success(request, result['message'])
            _log_dns(request.user, 'rollback', 'backup', str(backup),
                     detail=result['message'], result='success')
        else:
            messages.error(request, f'回滚失败: {result["message"]}')
            _log_dns(request.user, 'rollback_failed', 'backup', str(backup),
                     detail=result['message'], result='failed')
        return redirect('dns:backup_list')

    context = {'backup': backup}
    return render(request, 'dns/backup.html', context)


@login_required
def api_manual_backup(request):
    """API: 手动创建备份快照"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持POST'})

    from .services.config_renderer import ConfigRenderer

    try:
        renderer = ConfigRenderer(_get_server())
        config_text = renderer.render_full_config()

        backup = DnsBackup.objects.create(
            version=None,
            backup_type='manual',
            config_content=config_text,
            file_size=len(config_text),
            storage_path='',
            backup_user=request.user,
            notes=request.POST.get('notes', '手动备份'),
        )

        _log_dns(request.user, 'manual_backup', 'backup',
                 f'手动备份 #{backup.pk}', detail='创建手动配置快照')
        return JsonResponse({
            'success': True,
            'message': f'手动备份 #{backup.pk} 已创建',
            'backup_id': backup.pk,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ====================================================================
# 14. 审计日志
# ====================================================================
@login_required
def audit_log_list(request):
    """DNS审计日志列表 - 支持多维度筛选和分页"""
    logs_qs = DnsAuditLog.objects.select_related('user').all()

    category = request.GET.get('category', '')
    action = request.GET.get('action', '')
    search = request.GET.get('search', '')

    # 筛选
    if category:
        logs_qs = logs_qs.filter(category=category)
    if action:
        logs_qs = logs_qs.filter(action=action)
    if search:
        logs_qs = logs_qs.filter(
            Q(object_name__icontains=search) |
            Q(detail__icontains=search) |
            Q(new_value__icontains=search) |
            Q(old_value__icontains=search)
        )

    # 排序+分页
    logs_qs = logs_qs.order_by('-operation_time')
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    paginator = Paginator(logs_qs, 50)
    page = request.GET.get('page', 1)
    try:
        logs = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        logs = paginator.page(1)

    # 统计摘要
    total_count = logs_qs.count()
    success_count = logs_qs.filter(result='success').count()
    failed_count = logs_qs.filter(result='failed').count()

    context = {
        'logs': logs,
        'paginator': paginator,
        'categories': DnsAuditLog.CATEGORY_CHOICES,
        'actions': DnsAuditLog.ACTION_CHOICES,
        'current_category': category,
        'current_action': action,
        'search': search,
        'total_count': total_count,
        'success_count': success_count,
        'failed_count': failed_count,
    }
    return render(request, 'dns/audit.html', context)


@login_required
def api_audit_detail(request, pk):
    """API: 获取单条审计日志的详细变更对比（AJAX）"""
    log = get_object_or_404(DnsAuditLog.objects.select_related('user'), pk=pk)
    return JsonResponse({
        'id': log.pk,
        'user': str(log.user),
        'action': log.action,
        'category': log.category,
        'category_display': log.get_category_display(),
        'object_name': log.object_name,
        'detail': log.detail,
        'old_value': log.old_value,
        'new_value': log.new_value,
        'result': log.result,
        'client_ip': log.client_ip,
        'operation_time': log.operation_time.strftime('%Y-%m-%d %H:%M:%S') if log.operation_time else '',
    })
