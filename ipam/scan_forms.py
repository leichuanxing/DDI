"""
IPAM 探测功能表单
"""

from django import forms
from ipam.scan_models import ScanTask, DiscoveryRule
from ipam.models import Subnet


class ScanTaskForm(forms.ModelForm):
    """扫描任务创建表单"""
    
    class Meta:
        model = ScanTask
        fields = ['name', 'task_type', 'target_type', 'subnet', 'start_ip', 'end_ip',
                  'ping_count', 'ping_timeout', 'ports', 'concurrent']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: 办公网Ping扫描'
            }),
            'task_type': forms.Select(attrs={'class': 'form-select'}),
            'target_type': forms.Select(attrs={'class': 'form-select', 'id': 'target_type_select'}),
            'subnet': forms.Select(attrs={'class': 'form-select'}),
            'start_ip': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: 192.168.1.1'
            }),
            'end_ip': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: 192.168.1.254'
            }),
            'ping_count': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 10
            }),
            'ping_timeout': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0.1,
                'max': 5,
                'step': 0.1
            }),
            'ports': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '22,80,443 或 1-1024'
            }),
            'concurrent': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 10,
                'max': 500
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = '任务名称'
        self.fields['task_type'].label = '扫描类型'
        self.fields['target_type'].label = '目标类型'
        self.fields['subnet'].label = '目标子网'
        self.fields['start_ip'].label = '起始IP'
        self.fields['end_ip'].label = '结束IP'
        self.fields['ping_count'].label = 'Ping次数'
        self.fields['ping_timeout'].label = '超时(秒)'
        self.fields['ports'].label = '扫描端口'
        self.fields['concurrent'].label = '并发数'
        
        # 设置帮助文本
        self.fields['ping_count'].help_text = '每个IP发送的ICMP请求数量(1-10)'
        self.fields['ping_timeout'].help_text = '单次Ping超时时间，值越小越快但可能漏报'
        self.fields['ports'].help_text = '逗号分隔或范围表示，如: 22,80,443,3389 或 1-1000'
        self.fields['concurrent'].help_text = '同时扫描的主机数量，建议50-200'
        
        # 只显示有效的子网
        self.fields['subnet'].queryset = Subnet.objects.all()
        self.fields['subnet'].empty_label = '-- 选择子网 --'
    
    def clean(self):
        cleaned_data = super().clean()
        target_type = cleaned_data.get('target_type')
        
        if target_type == 'subnet':
            if not cleaned_data.get('subnet'):
                raise forms.ValidationError({'subnet': '选择子网类型时必须指定目标子网'})
        elif target_type == 'range':
            if not cleaned_data.get('start_ip') or not cleaned_data.get('end_ip'):
                raise forms.ValidationError({'start_ip': '指定IP范围时需要填写起始和结束IP'})
            
            # 验证IP格式
            try:
                from common.ip_utils import ip_to_int
                start = ip_to_int(cleaned_data.get('start_ip'))
                end = ip_to_int(cleaned_data.get('end_ip'))
                if abs(end - start) > 65534:
                    raise forms.ValidationError('IP范围过大，单次最多扫描65535个地址')
            except Exception as e:
                raise forms.ValidationError(str(e))
                
        elif target_type == 'single':
            if not cleaned_data.get('start_ip'):
                raise forms.ValidationError({'start_ip': '单个IP模式时需要填写IP地址'})
        
        task_type = cleaned_data.get('task_type')
        ports = cleaned_data.get('ports')
        
        if task_type in ('port', 'full') and not ports:
            raise forms.ValidationError({'ports': '端口扫描或综合扫描时需要指定端口'})
        
        return cleaned_data


class DiscoveryRuleForm(forms.ModelForm):
    """自动发现规则表单"""
    
    class Meta:
        model = DiscoveryRule
        fields = ['name', 'subnet', 'scan_types', 'ports', 'schedule', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'subnet': forms.Select(attrs={'class': 'form-select'}),
            'scan_types': forms.CheckboxSelectMultiple(),
            'ports': forms.TextInput(attrs={'class': 'form-control'}),
            'schedule': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['scan_types'].choices = (
            ('ping', 'Ping 探测'),
            ('port', '端口扫描'),
            ('arp', 'ARP 扫描'),
        )
