from django import forms
from .models import Region, VLAN, Subnet, IPAddress


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class VLANForm(forms.ModelForm):
    class Meta:
        model = VLAN
        fields = ['vlan_id', 'name', 'region', 'purpose', 'gateway', 'description']
        widgets = {
            'vlan_id': forms.NumberInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'region': forms.Select(attrs={'class': 'form-select'}),
            'purpose': forms.TextInput(attrs={'class': 'form-control'}),
            'gateway': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class SubnetForm(forms.ModelForm):
    class Meta:
        model = Subnet
        fields = ['name', 'cidr', 'gateway', 'region', 'vlan', 'purpose', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'cidr': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '例如: 192.168.10.0/24'}),
            'gateway': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '例如: 192.168.10.1'}),
            'region': forms.Select(attrs={'class': 'form-select'}),
            'vlan': forms.Select(attrs={'class': 'form-select'}),
            'purpose': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def clean_cidr(self):
        cidr = self.cleaned_data['cidr']
        from common.ip_utils import validate_cidr
        if not validate_cidr(cidr):
            raise forms.ValidationError('无效的CIDR格式，请输入正确的网段地址，例如: 192.168.10.0/24')
        
        # 自动计算掩码位数
        if '/' in cidr:
            prefix_len = int(cidr.split('/')[1])
            self.instance.prefix_len = prefix_len
        
        return cidr
    
    def clean_gateway(self):
        gateway = self.cleaned_data.get('gateway')
        cidr = self.cleaned_data.get('cidr')
        
        if gateway and cidr:
            from common.ip_utils import ip_in_network
            if not ip_in_network(gateway, cidr):
                raise forms.ValidationError(f'网关地址 {gateway} 不在子网 {cidr} 范围内')
        
        return gateway


class IPAddressAllocateForm(forms.ModelForm):
    """IP分配表单"""
    class Meta:
        model = IPAddress
        fields = ['hostname', 'mac_address', 'device_name', 'owner', 'department', 
                  'device_type', 'binding_type', 'notes']
        widgets = {
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'mac_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'XX:XX:XX:XX:XX:XX'}),
            'device_name': forms.TextInput(attrs={'class': 'form-control'}),
            'owner': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'device_type': forms.Select(attrs={'class': 'form-select',
                'choices': [('', '-- 请选择 --')] + [(t, t) for t in [
                    '服务器', 'PC', '笔记本', '打印机', '交换机', 
                    '路由器', '防火墙', '摄像头', 'AP', '其他'
                ]]}),
            'binding_type': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def clean_mac_address(self):
        mac = self.cleaned_data.get('mac_address', '')
        if mac:
            import re
            mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
            if not mac_pattern.match(mac):
                raise forms.ValidationError('MAC地址格式不正确，应为 XX:XX:XX:XX:XX:XX 格式')
        return mac


class IPBatchAllocateForm(forms.Form):
    """批量分配表单"""
    start_ip = forms.GenericIPAddressField(label='起始IP', widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '例如: 192.168.10.10'
    }))
    end_ip = forms.GenericIPAddressField(label='结束IP', widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '例如: 192.168.10.20'
    }))
    device_type = forms.CharField(label='设备类型', required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    department = forms.CharField(label='部门', required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    notes = forms.CharField(label='备注', required=False, widget=forms.Textarea(attrs={
        'class': 'form-control', 'rows': 3
    }))


class IPSearchForm(forms.Form):
    """IP搜索表单"""
    search = forms.CharField(required=False, label='搜索', widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '搜索IP、主机名、MAC、设备名...'
    }))
    status = forms.ChoiceField(required=False, choices=[('', '全部状态')] + list(IPAddress.STATUS_CHOICES),
                               widget=forms.Select(attrs={'class': 'form-select'}))
    subnet = forms.ModelChoiceField(queryset=Subnet.objects.all(), required=None,
                                     empty_label='全部子网',
                                     widget=forms.Select(attrs={'class': 'form-select'}))
