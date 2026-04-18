from django import forms
from .models import DHCPPool, DHCPExclusion, DHCPLease


class DHCPPoolForm(forms.ModelForm):
    class Meta:
        model = DHCPPool
        fields = ['name', 'subnet', 'start_address', 'end_address', 'gateway',
                  'dns_servers', 'lease_time', 'status', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'subnet': forms.Select(attrs={'class': 'form-select', 'id': 'subnet_select'}),
            'start_address': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': '例如: 192.168.10.100'
            }),
            'end_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: 192.168.10.200'
            }),
            'gateway': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '可选，默认使用子网网关'
            }),
            'dns_servers': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: 8.8.8.8, 8.8.4.4 或留空'
            }),
            'lease_time': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        subnet = cleaned_data.get('subnet')
        start_addr = cleaned_data.get('start_address')
        end_addr = cleaned_data.get('end_address')
        
        if subnet and start_addr and end_addr:
            # 验证地址范围在子网内
            from common.ip_utils import ip_in_network
            if not ip_in_network(start_addr, subnet.cidr):
                raise forms.ValidationError(f'起始地址 {start_addr} 不在子网 {subnet.cidr} 范围内')
            
            if not ip_in_network(end_addr, subnet.cidr):
                raise forms.ValidationError(f'结束地址 {end_addr} 不在子网 {subnet.cidr} 范围内')
            
            # 验证起始 <= 结束
            import ipaddress
            if int(ipaddress.ip_address(start_addr)) > int(ipaddress.ip_address(end_addr)):
                raise forms.ValidationError('起始地址不能大于结束地址')
        
        return cleaned_data


class DHCPExclusionForm(forms.ModelForm):
    class Meta:
        model = DHCPExclusion
        fields = ['pool', 'start_ip', 'end_ip', 'reason', 'notes']
        widgets = {
            'pool': forms.Select(attrs={'class': 'form-select'}),
            'start_ip': forms.TextInput(attrs={'class': 'form-control'}),
            'end_ip': forms.TextInput(attrs={'class': 'form-control'}),
            'reason': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        pool = cleaned_data.get('pool')
        start_ip = cleaned_data.get('start_ip')
        end_ip = cleaned_data.get('end_ip')
        
        if pool and start_ip and end_ip:
            # 验证排除范围在地址池内
            import ipaddress
            pool_start = int(ipaddress.ip_address(pool.start_address))
            pool_end = int(ipaddress.ip_address(pool.end_address))
            excl_start = int(ipaddress.ip_address(start_ip))
            excl_end = int(ipaddress.ip_address(end_ip))
            
            if excl_start < pool_start or excl_end > pool_end:
                raise forms.ValidationError(f'排除地址范围必须在地址池 {pool.start_address}-{pool.end_address} 内')
            
            if excl_start > excl_end:
                raise forms.ValidationError('起始IP不能大于结束IP')
        
        return cleaned_data


class DHCPLeaseForm(forms.ModelForm):
    class Meta:
        model = DHCPLease
        fields = ['ip_address', 'mac_address', 'hostname', 'device_identifier',
                  'start_time', 'end_time', 'status', 'pool']
        widgets = {
            'ip_address': forms.TextInput(attrs={'class': 'form-control'}),
            'mac_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'XX:XX:XX:XX:XX:XX'
            }),
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'device_identifier': forms.TextInput(attrs={'class': 'form-control'}),
            'start_time': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'end_time': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'pool': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def clean_mac_address(self):
        mac = self.cleaned_data.get('mac_address', '')
        if mac:
            import re
            mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
            if not mac_pattern.match(mac):
                raise forms.ValidationError('MAC地址格式不正确')
        return mac


class DHCPLeaseSearchForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '搜索IP、MAC或主机名...'
    }))
    status = forms.ChoiceField(
        required=False,
        choices=[('', '全部状态')] + list(DHCPLease.STATUS_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    pool = forms.ModelChoiceField(
        queryset=DHCPPool.objects.all(),
        required=None,
        empty_label='全部地址池',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
