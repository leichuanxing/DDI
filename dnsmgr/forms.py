from django import forms
from .models import DNSZone, DNSRecord, DNSSettings


class DNSSettingsForm(forms.ModelForm):
    """DNS全局配置表单"""
    class Meta:
        model = DNSSettings
        fields = ['enable_forward', 'forwarders', 'listen_port', 'listen_address',
                  'default_ttl', 'enable_cache', 'cache_ttl']
        widgets = {
            'enable_forward': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'forwarders': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '8.8.8.8, 114.114.114.114'
            }),
            'listen_port': forms.NumberInput(attrs={'class': 'form-control'}),
            'listen_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '0.0.0.0 表示所有接口'
            }),
            'default_ttl': forms.NumberInput(attrs={'class': 'form-control'}),
            'enable_cache': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'cache_ttl': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def clean_forwarders(self):
        forwarders = self.cleaned_data.get('forwarders', '').strip()
        if not forwarders:
            return ''
        ips = [ip.strip() for ip in forwarders.split(',') if ip.strip()]
        for ip in ips:
            from common.ip_utils import is_valid_ip
            if not is_valid_ip(ip):
                raise forms.ValidationError(f'无效的IP地址: {ip}')
        return ', '.join(ips)

    def clean_listen_port(self):
        port = self.cleaned_data.get('listen_port', 53)
        if port < 1 or port > 65535:
            raise forms.ValidationError('端口范围: 1-65535')
        return port


class DNSZoneForm(forms.ModelForm):
    class Meta:
        model = DNSZone
        fields = ['name', 'zone_type', 'primary_dns', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '正向: example.com, 反向: 10.168.192.in-addr.arpa'
            }),
            'zone_type': forms.Select(attrs={'class': 'form-select'}),
            'primary_dns': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class DNSRecordForm(forms.ModelForm):
    class Meta:
        model = DNSRecord
        fields = ['name', 'record_type', 'value', 'ttl', 'zone', 'linked_ip',
                  'probe_port', 'priority', 'status', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: www 或 @ 表示根'
            }),
            'record_type': forms.Select(attrs={
                'class': 'form-select',
                'id': 'record_type_select'
            }),
            'value': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 2,
                'placeholder': 'A记录填IP地址，CNAME填目标域名...'
            }),
            'ttl': forms.NumberInput(attrs={'class': 'form-control'}),
            'zone': forms.Select(attrs={'class': 'form-select'}),
            'linked_ip': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '仅A/AAAA记录需要填写',
                'id': 'id_linked_ip'
            }),
            'probe_port': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '如 22,80,443',
                'min': '1',
                'max': '65535',
                'id': 'id_probe_port'
            }),
            'priority': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'MX记录优先级'
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        record_type = self.cleaned_data.get('record_type', '')
        
        # 基本校验
        if not name:
            raise forms.ValidationError('记录名称不能为空')
        
        # PTR记录特殊处理：应该是反写的IP
        if record_type == 'PTR':
            if not '.' in name and '-' not in name:
                # 可能是简单格式，尝试转换
                pass
        
        return name
    
    def clean_value(self):
        value = self.cleaned_data['value'].strip()
        record_type = self.cleaned_data.get('record_type', '')
        
        if not value:
            raise forms.ValidationError('记录值不能为空')
        
        # A记录校验IP格式
        if record_type == 'A':
            from common.ip_utils import is_valid_ip
            if not is_valid_ip(value):
                raise forms.ValidationError(f'A记录的值必须是有效的IPv4地址: {value}')
        
        # AAAA记录校验
        elif record_type == 'AAAA':
            from common.ip_utils import is_valid_ip
            if not is_valid_ip(value):
                raise forms.ValidationError(f'AAAA记录的值必须是有效的IPv6地址: {value}')
        
        # MX记录校验优先级格式
        elif record_type == 'MX':
            parts = value.split()
            if len(parts) < 2:
                raise forms.ValidationError('MX记录格式应为: 优先级 域名，例如: 10 mail.example.com')
        
        return value
    
    def clean_linked_ip(self):
        ip = self.cleaned_data.get('linked_ip')
        record_type = self.cleaned_data.get('record_type', '')
        
        if ip and record_type not in ['A', 'AAAA']:
            # 非A/AAAA记录不应该有关联IP
            return None
        
        if ip:
            from common.ip_utils import is_valid_ip
            if not is_valid_ip(ip):
                raise forms.ValidationError('无效的IP地址格式')
        
        return ip


class DNSRecordSearchForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '搜索记录名称或值...'
    }))
    record_type = forms.ChoiceField(
        required=False,
        choices=[('', '全部类型')] + list(DNSRecord.RECORD_TYPE_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    zone = forms.ModelChoiceField(
        queryset=DNSZone.objects.all(),
        required=None,
        empty_label='全部区域',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', '全部状态')] + list(DNSRecord.STATUS_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class DNSQueryLogSearchForm(forms.Form):
    """DNS解析日志搜索表单"""
    search = forms.CharField(required=False, label='域名/IP',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '搜索查询域名或客户端IP...'
        }))
    query_type = forms.ChoiceField(required=False, label='查询类型',
        choices=[('', '全部类型'), ('A', 'A'), ('AAAA', 'AAAA'),
                 ('CNAME', 'CNAME'), ('MX', 'MX'), ('PTR', 'PTR'),
                 ('TXT', 'TXT'), ('NS', 'NS')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    result_source = forms.ChoiceField(required=False, label='结果来源',
        choices=[('', '全部来源'), ('local', '本地解析'), ('forward', '外部转发'),
                 ('cache', '缓存命中'), ('nxdomain', 'NXDOMAIN'), ('servfail', 'SERVFAIL')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
