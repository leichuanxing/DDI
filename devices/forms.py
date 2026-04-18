from django import forms
from .models import Device


class DeviceForm(forms.ModelForm):
    DEVICE_TYPES = [
        ('server', '服务器'), ('pc', 'PC'), ('laptop', '笔记本'),
        ('printer', '打印机'), ('switch', '交换机'), ('router', '路由器'),
        ('firewall', '防火墙'), ('camera', '摄像头'), ('ap', '无线AP'),
        ('storage', '存储设备'), ('other', '其他')
    ]
    
    class Meta:
        model = Device
        fields = ['hostname', 'device_name', 'device_type', 'manager', 'department',
                  'mac_address', 'operating_system', 'region', 'description']
        widgets = {
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'device_name': forms.TextInput(attrs={'class': 'form-control'}),
            'device_type': forms.Select(attrs={
                'class': 'form-select',
            }),
            'manager': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'mac_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'XX:XX:XX:XX:XX:XX'
            }),
            'operating_system': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如: CentOS 7, Windows Server 2019'
            }),
            'region': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['device_type'].widget.choices = [('', '-- 请选择 --')] + self.DEVICE_TYPES
    
    def clean_mac_address(self):
        mac = self.cleaned_data.get('mac_address', '')
        if mac:
            import re
            mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
            if not mac_pattern.match(mac):
                raise forms.ValidationError('MAC地址格式不正确')
        return mac


class DeviceSearchForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '搜索主机名、设备名称或MAC...'
    }))
    device_type = forms.ChoiceField(
        required=False,
        choices=[('', '全部类型')] + [
            (t[0], t[1]) for t in Device.DEVICE_TYPE_CHOICES
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    region = forms.ModelChoiceField(
        queryset=None,
        required=None,
        empty_label='全部区域',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from ipam.models import Region
        self.fields['region'].queryset = Region.objects.all()
