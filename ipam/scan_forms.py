"""
IPAM 探测功能表单
"""

from django import forms
from ipam.scan_models import ScanTask, DiscoveryRule, SwitchDevice
from ipam.models import Subnet


class SwitchDeviceForm(forms.ModelForm):
    """交换机设备配置表单 - SSH连接信息"""
    
    class Meta:
        model = SwitchDevice
        fields = ['name', 'vendor', 'ip_address', 'port', 'username',
                  'password', 'enable_password', 'subnet', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '例: 核心交换机-SW01'}),
            'vendor': forms.Select(attrs={'class': 'form-select'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.1'}),
            'port': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 65535}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SSH登录用户名'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '密码或密钥路径'}),
            'enable_password': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enable特权密码(可选)'}),
            'subnet': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = '设备名称'
        self.fields['vendor'].label = '设备厂商'
        self.fields['ip_address'].label = '管理IP地址'
        self.fields['port'].label = 'SSH端口'
        self.fields['username'].label = '用户名'
        self.fields['password'].label = '密码'
        self.fields['enable_password'].label = 'Enable特权密码'
        self.fields['subnet'].label = '管理子网（可选）'
        self.fields['is_active'].label = '启用'
        
        self.fields['port'].help_text = '默认22'
        self.fields['password'].help_text = '支持密码或SSH私钥文件路径'
        self.fields['enable_password'].help_text = 'Cisco/Huawei等需要enable权限才能执行show命令'
        
        self.fields['subnet'].queryset = Subnet.objects.all()
        self.fields['subnet'].empty_label = '-- 不关联子网 --'


class ScanTaskForm(forms.ModelForm):
    """扫描任务创建表单 - 配置扫描类型、目标范围、Ping参数和端口"""
    
    class Meta:
        model = ScanTask
        fields = ['name', 'task_type', 'target_type', 'subnet', 'start_ip', 'end_ip',
                  'ping_count', 'ping_timeout', 'ports', 'concurrent',
                  'switch_device', 'switch_command']
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
        # 设置各字段的中文标签
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
        self.fields['switch_device'].label = '目标交换机'
        self.fields['switch_command'].label = 'ARP命令'
        
        # 设置帮助文本
        self.fields['ping_count'].help_text = '每个IP发送的ICMP请求数量(1-10)'
        self.fields['ping_timeout'].help_text = '单次Ping超时时间，值越小越快但可能漏报'
        self.fields['ports'].help_text = '逗号分隔或范围表示，如: 22,80,443,3389 或 1-1000'
        self.fields['concurrent'].help_text = '同时扫描的主机数量，建议50-200'
        self.fields['switch_device'].help_text = '选择要获取ARP信息的交换机设备'
        self.fields['switch_command'].help_text = '默认 show arp，一般无需修改'
        
        # 只显示有效的子网
        self.fields['subnet'].queryset = Subnet.objects.all()
        self.fields['subnet'].empty_label = '-- 选择子网 --'
        
        # 交换机设备
        self.fields['switch_device'].queryset = SwitchDevice.objects.filter(is_active=True)
        self.fields['switch_device'].empty_label = '-- 请先添加交换机 --'
    
    def clean(self):
        """自定义校验 - 根据目标类型验证必填字段，检查IP范围和端口配置"""
        cleaned_data = super().clean()
        target_type = cleaned_data.get('target_type')
        task_type = cleaned_data.get('task_type')

        # 交换机ARP获取不需要目标类型相关校验
        if task_type == 'switch_arp':
            if not cleaned_data.get('switch_device'):
                raise forms.ValidationError({'switch_device': '交换机ARP获取必须选择目标交换机'})
            return cleaned_data

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

        ports = cleaned_data.get('ports')

        if task_type in ('port', 'full') and not ports:
            raise forms.ValidationError({'ports': '端口扫描或综合扫描时需要指定端口'})

        return cleaned_data


class DiscoveryRuleForm(forms.ModelForm):
    """自动发现规则表单 - 配置定时扫描规则的目标子网和调度周期"""
    
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
