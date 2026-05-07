from django import forms

from .models import DHCP4_OPTION_NAMES, DHCPOption, DHCPPool, DHCPSubnet


class DHCPOptionForm(forms.ModelForm):
    scope_object = forms.ChoiceField(label='作用域对象', required=False)

    class Meta:
        model = DHCPOption
        fields = ['scope_type', 'scope_object', 'option_code', 'option_name', 'option_value', 'description']
        widgets = {
            'scope_type': forms.Select(attrs={'data-option-scope': 'type'}),
            'option_code': forms.NumberInput(attrs={'min': 1, 'max': 255, 'placeholder': '例如 6'}),
            'option_name': forms.TextInput(attrs={'placeholder': '例如 domain-name-servers'}),
            'option_value': forms.Textarea(attrs={'rows': 3, 'placeholder': '例如 192.168.31.1 或 example.com'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': '可选，记录用途或变更说明'}),
        }
        labels = {
            'scope_type': '作用域类型',
            'option_code': 'Option Code',
            'option_name': 'Option Name',
            'option_value': 'Option Value',
            'description': '描述',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['scope_type'].choices = DHCPOption.SCOPE_CHOICES
        choices = [('', '全局作用域，不需要选择对象')]
        choices.extend(
            (f'subnet:{item.id}', f'子网：{item.subnet} / ID {item.subnet_id}')
            for item in DHCPSubnet.objects.order_by('subnet_id', 'subnet')
        )
        choices.extend(
            (f'pool:{item.id}', f'地址池：{item.dhcp_subnet.subnet} / {item.pool_start} - {item.pool_end}')
            for item in DHCPPool.objects.select_related('dhcp_subnet').order_by('dhcp_subnet__subnet_id', 'pool_start')
        )
        self.fields['scope_object'].choices = choices
        if self.instance and self.instance.pk and self.instance.scope_id:
            self.initial['scope_object'] = f'{self.instance.scope_type}:{self.instance.scope_id}'
        elif self.instance and self.instance.pk:
            self.initial['scope_object'] = ''
        self.fields['option_code'].help_text = '常用：3 routers，6 DNS Server，15 Domain Name，42 NTP Server，66 TFTP Server，67 Boot File。'
        self.fields['option_name'].help_text = 'Kea 使用的 Option 名称，需和 Option Code 匹配。'
        self.fields['option_value'].help_text = '多个地址用英文逗号分隔，例如：192.168.31.1,192.168.31.2。'

    def clean(self):
        cleaned = super().clean()
        scope_type = cleaned.get('scope_type')
        scope_object = cleaned.get('scope_object') or ''
        option_code = cleaned.get('option_code')
        if option_code in DHCP4_OPTION_NAMES and not cleaned.get('option_name'):
            cleaned['option_name'] = DHCP4_OPTION_NAMES[option_code]
        if scope_type == 'global':
            self.instance.scope_id = None
            return cleaned
        expected_prefix = f'{scope_type}:'
        if not scope_object.startswith(expected_prefix):
            raise forms.ValidationError('请选择和作用域类型匹配的子网或地址池。')
        self.instance.scope_id = int(scope_object.split(':', 1)[1])
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.scope_id = self.instance.scope_id
        obj.full_clean()
        if commit:
            obj.save()
            self.save_m2m()
        return obj
