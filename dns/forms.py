"""
DNS管理模块 - 表单定义
提供全局配置、ACL、View、Zone、资源记录等全部表单
P5增强: DnsRecordForm添加完整clean方法进行业务规则校验
"""

import re
import ipaddress
from django import forms
from django.core.exceptions import ValidationError
from .models import (
    DnsServer, DnsGlobalOption, DnsAcl, DnsAclItem,
    DnsView, DnsZone, DnsRecord, DnsForwardRule,
)
from .utils.helpers import validate_record_value, is_valid_fqdn


# ============================================================
# 服务器表单
# ============================================================
class DnsServerForm(forms.ModelForm):
    class Meta:
        model = DnsServer
        fields = ['hostname', 'ip_address', 'bind_version', 'named_conf_path',
                   'zone_dir', 'log_file', 'is_local', 'enabled', 'description']
        widgets = {
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control'}),
            'bind_version': forms.TextInput(attrs={'class': 'form-control', 'readonly': True}),
            'named_conf_path': forms.TextInput(attrs={'class': 'form-control'}),
            'zone_dir': forms.TextInput(attrs={'class': 'form-control'}),
            'log_file': forms.TextInput(attrs={'class': 'form-control'}),
            'is_local': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


# ============================================================
# 全局配置表单
# ============================================================
class DnsGlobalOptionForm(forms.ModelForm):
    class Meta:
        model = DnsGlobalOption
        fields = [
            'directory', 'pid_file', 'dump_file', 'statistics_file',
            'listen_on_v4', 'listen_on_v6',
            'allow_query', 'allow_recursion', 'recursion',
            'dnssec_validation', 'auth_nxdomain', 'empty_zones_enable',
            'forward_policy', 'forwarders',
            'querylog_enable', 'max_cache_size', 'version_hide',
            'raw_config'
        ]
        widgets = {
            'directory': forms.TextInput(attrs={'class': 'form-control'}),
            'pid_file': forms.TextInput(attrs={'class': 'form-control'}),
            'dump_file': forms.TextInput(attrs={'class': 'form-control'}),
            'statistics_file': forms.TextInput(attrs={'class': 'form-control'}),
            'listen_on_v4': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'placeholder': '每行一个IP，如:\nany\n127.0.0.1\n192.168.1.0/24'
            }),
            'listen_on_v6': forms.Select(attrs={'class': 'form-select'},
                                          choices=[('::1', '::1 (仅本地)'), ('any', 'any (所有)')]),
            'allow_query': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': '每行一个: any / localhost / IP/CIDR / ACL名'
            }),
            'allow_recursion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'recursion': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'dnssec_validation': forms.Select(attrs={'class': 'form-select'}),
            'auth_nxdomain': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'empty_zones_enable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'forward_policy': forms.Select(attrs={'class': 'form-select'}, choices=[
                ('', '不转发'), ('only', '仅转发(only)'), ('first', '优先转发(first)')
            ]),
            'forwarders': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': '8.8.8.8\n114.114.114.114\n223.5.5.5'
            }),
            'querylog_enable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_cache_size': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '512M'}),
            'version_hide': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'raw_config': forms.Textarea(attrs={
                'class': 'form-control font-monospace', 'rows': 6,
                'placeholder': '高级配置片段，将直接追加到options{}块末尾...'
            }),
        }

    def clean_listen_on_v4(self):
        """校验IPv4监听地址格式"""
        data = self.cleaned_data.get('listen_on_v4', '').strip()
        if not data:
            return data
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower() == 'any':
                continue
            if '/' in line:
                # CIDR格式
                try:
                    ipaddress.IPv4Network(line, strict=False)
                except ValueError:
                    raise ValidationError(f'无效的IPv4地址或CIDR: {line}')
            else:
                # 单IP格式
                try:
                    ipaddress.IPv4Address(line)
                except ValueError:
                    raise ValidationError(f'无效的IPv4地址: {line}')
        return data

    def clean_forwarders(self):
        """校验上游转发DNS IP列表"""
        data = self.cleaned_data.get('forwarders', '').strip()
        if not data:
            return data
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ipaddress.ip_address(line)  # 同时支持IPv4和IPv6
            except ValueError:
                raise ValidationError(f'无效的转发器IP地址: {line}')
        return data


# ============================================================
# ACL 表单
# ============================================================
class DnsAclForm(forms.ModelForm):
    class Meta:
        model = DnsAcl
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        reserved = {'any', 'none', 'localhost', 'localnets'}
        if name.lower() in reserved:
            raise forms.ValidationError(f'"{name}" 是保留的内置名称，请使用其他名称')
        # 名称只能包含字母数字连字符下划线
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', name):
            raise forms.ValidationError('ACL名称必须以字母开头，仅允许字母、数字、连字符和下划线')
        return name


class DnsAclItemForm(forms.ModelForm):
    class Meta:
        model = DnsAclItem
        fields = ['item_type', 'value']
        widgets = {
            'item_type': forms.Select(attrs={'class': 'form-select'}),
            'value': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'IP/网段/密钥名等'}),
        }

    def clean_value(self):
        """根据条目类型校验值"""
        item_type = self.cleaned_data.get('item_type', '')
        value = (self.cleaned_data.get('value') or '').strip()

        # 某些类型不需要值
        if item_type in ('any', 'none', 'localhost', 'localnets'):
            return value

        if not value:
            raise forms.ValidationError('该类型的条目需要填写值')

        if item_type == 'ip':
            try:
                ipaddress.IPv4Address(value)
            except ValueError:
                raise forms.ValidationError(f'无效的IPv4地址: {value}')
        elif item_type == 'ipv6':
            try:
                ipaddress.IPv6Address(value)
            except ValueError:
                raise forms.ValidationError(f'无效的IPv6地址: {value}')
        elif item_type == 'cidr':
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError:
                raise forms.ValidationError(f'无效的CIDR网段: {value}')

        return value


DnsAclItemFormSet = forms.modelformset_factory(
    DnsAclItem, form=DnsAclItemForm, extra=3, can_delete=True
)


# ============================================================
# View 表单
# ============================================================
class DnsViewForm(forms.ModelForm):
    class Meta:
        model = DnsView
        fields = ['name', 'match_clients', 'match_destinations', 'recursion',
                   'allow_query_acl', 'allow_recursion_acl', 'description', 'order_index']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'match_clients': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 4}),
            'match_destinations': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 4}),
            'recursion': forms.NullBooleanSelect(),
            'allow_query_acl': forms.Select(attrs={'class': 'form-select'}),
            'allow_recursion_acl': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'order_index': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', name):
            raise forms.ValidationError(
                'View名称必须以字母开头，仅允许字母、数字、连字符和下划线'
            )
        return name


# ============================================================
# Zone 表单（核心）
# ============================================================
class DnsZoneForm(forms.ModelForm):
    class Meta:
        model = DnsZone
        fields = [
            'name', 'zone_type', 'direction_type', 'view',
            'file_name', 'default_ttl',
            'primary_ns', 'admin_mail', 'serial_no',
            'refresh', 'retry', 'expire', 'minimum',
            'master_ips', 'slave_ips', 'forwarders', 'forward_policy',
            'allow_transfer_acl', 'allow_update_acl',
            'dynamic_update', 'enabled', 'description'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'example.com 或 10.168.192.in-addr.arpa'
            }),
            'zone_type': forms.Select(attrs={'class': 'form-select'}),
            'direction_type': forms.Select(attrs={'class': 'form-select'}),
            'view': forms.Select(attrs={'class': 'form-select'}),
            'file_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '留空自动生成，如 zone.example_com'
            }),
            'default_ttl': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3600'}),
            'primary_ns': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'ns1.example.com.'
            }),
            'admin_mail': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'admin@example.com 或 admin.example.com.'
            }),
            'serial_no': forms.NumberInput(attrs={'class': 'form-control'}),
            'refresh': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3600'}),
            'retry': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '600'}),
            'expire': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '86400'}),
            'minimum': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3600'}),
            'master_ips': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': 'Slave区: 填写Master IP，逗号分隔'
            }),
            'slave_ips': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': 'Master区: 允许AXFR的目标IP'
            }),
            'forwarders': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': '转发目标IP，逗号分隔'
            }),
            'forward_policy': forms.Select(attrs={'class': 'form-select'}),
            'allow_transfer_acl': forms.Select(attrs={'class': 'form-select'}),
            'allow_update_acl': forms.Select(attrs={'class': 'form-select'}),
            'dynamic_update': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_name(self):
        """校验区域名称格式"""
        name = self.cleaned_data.get('name', '').strip().rstrip('.')
        direction = self.cleaned_data.get('direction_type')
        if not name:
            raise forms.ValidationError('区域名称不能为空')

        if direction == 'reverse':
            if not (re.match(r'^\d+(-\d+)*\.in-addr\.arpa$', name) or
                    re.match(r'^[a-f0-9]+(-[a-f0-9]+)*\.ip6\.arpa$', name)):
                raise forms.ValidationError(f'无效的反向区域名称格式，应为 x.x.x.in-addr.arpa 格式')
        else:
            if '.' not in name or not re.match(
                r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)*$',
                name, re.I
            ):
                raise forms.ValidationError('无效的区域名称格式，应为合法域名如 example.com')

        return name

    def clean_admin_mail(self):
        """校验管理员邮箱(RNAME)格式"""
        mail = (self.cleaned_data.get('admin_mail') or '').strip()
        if not mail:
            return mail  # 可选字段
        # 支持两种格式: user@domain.com 或 user.domain.com.
        if '@' in mail:
            local, domain = mail.rsplit('@', 1)
            if not domain or '.' not in domain:
                raise forms.ValidationError('邮箱域名部分不合法')
        elif not mail.endswith('.'):
            raise forms.ValidationError('RNAME应以点结尾(如 admin.example.com.)')
        return mail

    def clean_serial_no(self):
        """校验SOA Serial号码格式"""
        serial = self.cleaned_data.get('serial_no')
        if serial is None:
            return 2026042401
        if serial < 0 or serial > 4294967295:
            raise forms.ValidationError('Serial号码范围 0 ~ 4294967295 (32位无符号整数)')
        return serial

    def clean_default_ttl(self):
        """校验TTL范围"""
        ttl = self.cleaned_data.get('default_ttl')
        if ttl is None:
            return 3600
        if ttl < 0 or ttl > 2147483647:
            raise forms.ValidationError('TTL范围 0 ~ 2147483647 (约68年最大值)')
        if ttl < 300:
            raise forms.ValidationError('建议TTL不小于300秒(5分钟)')
        return ttl

    def clean_master_ips(self):
        """校验主服务器IP列表(Slave区用)"""
        ztype = self.cleaned_data.get('zone_type')
        ips_str = (self.cleaned_data.get('master_ips') or '').strip()

        if ztype == 'slave' and not ips_str:
            raise forms.ValidationError('从区域(Slave)必须指定至少一个主服务器IP')

        if not ips_str:
            return ips_str

        for ip in [ip.strip() for ip in re.split(r'[,;\s]+', ips_str) if ip.strip()]:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise forms.ValidationError(f'无效的主服务器IP地址: {ip}')
        return ips_str

    def clean_forwarders(self):
        """校验转发目标IP列表(Forward/Stub区用)"""
        ztype = self.cleaned_data.get('zone_type')
        fwd_str = (self.cleaned_data.get('forwarders') or '').strip()

        if ztype in ('forward', 'stub') and not fwd_str:
            raise forms.ValidationError(f'{ztype}区域必须指定至少一个转发目标IP')

        if not fwd_str:
            return fwd_str

        for ip in [ip.strip() for ip in re.split(r'[,;\s\n]+', fwd_str) if ip.strip()]:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise forms.ValidationError(f'无效的转发器IP地址: {ip}')
        return fwd_str

    def clean(self):
        cleaned_data = super().clean()
        ztype = cleaned_data.get('zone_type')
        master_ips = cleaned_data.get('master_ips')
        forwarders = cleaned_data.get('forwarders')

        if ztype == 'slave' and not master_ips:
            raise forms.ValidationError({'master_ips': '从区域(Slave)必须指定主服务器IP'})
        if ztype in ('forward', 'stub') and not forwarders:
            raise forms.ValidationError({'forwarders': f'{ztype}区域必须指定转发目标'})

        return cleaned_data


# ============================================================
# 资源记录表单（核心 - P5增强校验）
# ============================================================
class DnsRecordForm(forms.ModelForm):
    """资源记录表单 - 包含完整的业务规则校验

    校验规则:
    - CNAME不能与同名其他记录并存(RFC 1912)
    - A记录值必须是合法IPv4
    - AAAA记录值必须是合法IPv6
    - MX必须有优先级(0-65535)，值必须为FQDN
    - SRV必须有优先级/权重/端口，值必须为FQDN
    - NS/PTR值应为FQDN
    - TXT值可含任意文本(引号包裹)
    """
    class Meta:
        model = DnsRecord
        fields = ['zone', 'record_type', 'name', 'ttl', 'value', 'priority', 'weight', 'port', 'enabled']
        widgets = {
            'zone': forms.HiddenInput(),
            'record_type': forms.Select(attrs={'class': 'form-select', 'id': 'record_type_select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@ 或 www 或 mail 等'}),
            'ttl': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '留空用默认TTL'}),
            'value': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '根据记录类型填写值'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'MX/SRV优先级'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SRV权重'}),
            'port': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SRV端口'}),
            'enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_record_type(self):
        rtype = self.cleaned_data.get('record_type', '')
        allowed = dict(DnsRecord.RECORD_TYPE_CHOICES).keys()
        if rtype not in allowed:
            raise forms.ValidationError(f'不支持的记录类型: {rtype}')
        return rtype

    def clean_name(self):
        """校验记录名称"""
        name = (self.cleaned_data.get('name') or '@').strip()
        record_type = self.cleaned_data.get('record_type', '')

        if not name:
            return '@'

        # 基本字符检查（不允许特殊字符）
        if any(c in name for c in (';', '"', "'", '\\', '(', ')')):
            raise forms.ValidationError('记录名称不允许包含 ; " \' \\ ( ) 等特殊字符')

        # 长度检查
        if len(name) > 255:
            raise forms.ValidationError('记录名称最长255个字符')

        # SOA记录名称通常为 @
        if record_type == 'SOA' and name != '@':
            pass  # SOA可以是@或其他值，不强制

        return name

    def clean_value(self):
        """根据记录类型执行严格的值格式校验"""
        value = (self.cleaned_data.get('value') or '').strip()
        record_type = self.cleaned_data.get('record_type', '')

        if not value:
            raise forms.ValidationError('记录值不能为空')

        # 使用helpers中的通用校验函数
        is_valid, error_msg = validate_record_value(record_type, value)
        if not is_valid:
            raise forms.ValidationError(error_msg)

        return value

    def clean_priority(self):
        """校验优先级字段(MX/SRV用)"""
        prio = self.cleaned_data.get('priority')
        record_type = self.cleaned_data.get('record_type', '')

        if record_type == 'MX' and prio is None:
            raise forms.ValidationError('MX记录必须设置优先级 (0-65535)')
        if prio is not None:
            if prio < 0 or prio > 65535:
                raise forms.ValidationError('优先级范围 0-65535')
        return prio

    def clean_weight(self):
        """校验权重字段(SRV用)"""
        weight = self.cleaned_data.get('weight')
        if weight is not None and (weight < 0 or weight > 65535):
            raise forms.ValidationError('权重范围 0-65535')
        return weight

    def clean_port(self):
        """校验端口字段(SRV用)"""
        port = self.cleaned_data.get('port')
        if port is not None and (port < 1 or port > 65535):
            raise forms.ValidationError('端口范围 1-65535')
        return port

    def clean_ttl(self):
        """校验TTL"""
        ttl = self.cleaned_data.get('ttl')
        if ttl is not None:
            if ttl < 0 or ttl > 2147483647:
                raise forms.ValidationError('TTL范围 0 ~ 2147483647')
            if ttl < 60 and ttl != 0:
                raise forms.ValidationError('建议TTL不小于60秒')
        return ttl

    def clean(self):
        """跨字段业务规则校验"""
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data

        record_type = cleaned_data.get('record_type', '')
        name = cleaned_data.get('name', '@').strip()

        # 安全获取 zone 实例（需要从 self.instance.zone 获取）
        zone_obj = None
        _inst = getattr(self, 'instance', None)
        if _inst is not None:
            zone_obj = getattr(_inst, 'zone', None)

        # CNAME 规则：CNAME不能与同名其他记录并存
        if record_type == 'CNAME' and zone_obj:
            _pk = getattr(_inst, 'pk', 0) or 0
            conflicts = DnsRecord.objects.filter(
                zone=zone_obj, name=name, enabled=True
            ).exclude(record_type='CNAME').exclude(pk=_pk)
            if conflicts.exists():
                conflict_types = list(conflicts.values_list('record_type', flat=True))
                raise forms.ValidationError({
                    'name': f'该名称已存在 {", ".join(conflict_types)} 记录，RFC规定不能与CNAME并存'
                })

        # 非 CNAME 规则：如果已有同名CNAME则不能添加其他记录
        if record_type != 'CNAME' and zone_obj:
            _pk = getattr(_inst, 'pk', 0) or 0
            cname_exists = DnsRecord.objects.filter(
                zone=zone_obj, record_type='CNAME', name=name, enabled=True
            ).exclude(pk=_pk)
            if cname_exists.exists():
                raise forms.ValidationError({
                    'name': f'该名称已存在CNAME记录，不能再添加 {record_type} 类型记录'
                })

        # SRV 记录需要所有三个数值字段
        if record_type == 'SRV':
            if cleaned_data.get('weight') is None:
                raise forms.ValidationError({'weight': 'SRV记录必须设置权重'})
            if cleaned_data.get('port') is None:
                raise forms.ValidationError({'port': 'SRV记录必须设置端口'})

        return cleaned_data


# ============================================================
# 转发规则表单
# ============================================================
class DnsForwardRuleForm(forms.ModelForm):
    class Meta:
        model = DnsForwardRule
        fields = ['rule_type', 'zone', 'forwarders', 'policy', 'enabled', 'description']
        widgets = {
            'rule_type': forms.Select(attrs={'class': 'form-select'}),
            'zone': forms.Select(attrs={'class': 'form-select'}),
            'forwarders': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'placeholder': '8.8.8.8\n114.114.114.114'
            }),
            'policy': forms.Select(attrs={'class': 'form-select'}),
            'enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_forwarders(self):
        """校验转发目标IP列表"""
        data = (self.cleaned_data.get('forwarders') or '').strip()
        if not data:
            raise forms.ValidationError('转发目标IP不能为空')
        for ip in [ip.strip() for ip in re.split(r'[,;\s\n]+', data) if ip.strip()]:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise forms.ValidationError(f'无效的IP地址: {ip}')
        return data

    def clean(self):
        cleaned_data = super().clean()
        rule_type = cleaned_data.get('rule_type', '')
        zone = cleaned_data.get('zone')

        # 条件转发必须关联Zone
        if rule_type == 'conditional' and not zone:
            raise forms.ValidationError({'zone': '条件转发必须关联一个Zone'})

        return cleaned_data


# ============================================================
# 搜索/筛选表单
# ============================================================
class ZoneSearchForm(forms.Form):
    search = forms.CharField(required=False, label='搜索', widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '搜索区域名称...'
    }))
    zone_type = forms.ChoiceField(required=False, choices=[('', '全部类型')] + list(DnsZone.ZONE_TYPE_CHOICES),
                                   widget=forms.Select(attrs={'class': 'form-select'}))
    direction_type = forms.ChoiceField(required=False, choices=[('', '全部方向')] + list(DnsZone.DIRECTION_CHOICES),
                                        widget=forms.Select(attrs={'class': 'form-select'}))
    enabled = forms.ChoiceField(required=False, choices=[('', '全部'), ('1', '启用'), ('0', '禁用')],
                                 widget=forms.Select(attrs={'class': 'form-select'}))


class RecordSearchForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '搜索名称或值...'
    }))
    record_type = forms.ChoiceField(required=False,
                                     choices=[('', '全部类型')] + list(DnsRecord.RECORD_TYPE_CHOICES),
                                     widget=forms.Select(attrs={'class': 'form-select'}))
    enabled = forms.ChoiceField(required=False, choices=[('', '全部'), ('1', '启用'), ('0', '禁用')],
                                 widget=forms.Select(attrs={'class': 'form-select'}))
