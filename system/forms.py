import json

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth import get_user_model

from accounts.models import Permission, Role
from .models import SystemConfig


class SystemUserForm(forms.ModelForm):
    password = forms.CharField(label='密码', required=False, widget=forms.PasswordInput(render_value=False))
    roles = forms.ModelMultipleChoiceField(
        label='角色',
        queryset=Role.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = get_user_model()
        fields = ['username', 'password', 'real_name', 'email', 'mobile', 'is_active', 'is_superuser', 'roles']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['roles'].initial = self.instance.roles.all()
            self.fields['password'].help_text = '留空则不修改当前密码。'
        else:
            self.fields['password'].required = True

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        roles = self.cleaned_data.get('roles')
        password = self.cleaned_data.get('password')
        user = super().save(commit=False)
        if password:
            user.set_password(password)
        elif user.pk:
            user.password = get_user_model().objects.only('password').get(pk=user.pk).password
        if commit:
            user.save()
            if roles is not None:
                user.roles.set(roles)
        return user


class SystemRoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        label='权限',
        queryset=Permission.objects.all().order_by('module', 'action'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Role
        fields = ['name', 'code', 'description', 'permissions']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['permissions'].initial = self.instance.permissions.all()

    def save(self, commit=True):
        permissions = self.cleaned_data.get('permissions')
        role = super().save(commit=False)
        if commit:
            role.save()
            if permissions is not None:
                role.permissions.set(permissions)
        return role


class SystemConfigForm(forms.ModelForm):
    value_text = forms.CharField(label='配置值 JSON', widget=forms.Textarea(attrs={'rows': 8}))

    class Meta:
        model = SystemConfig
        fields = ['key', 'value_text', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['value_text'].initial = json.dumps(self.instance.value or {}, ensure_ascii=False, indent=2)
        self.fields['value_text'].help_text = '请输入合法 JSON 对象，例如 {"enabled": true}。'

    def clean_value_text(self):
        value = self.cleaned_data.get('value_text') or '{}'
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f'JSON 格式错误：{exc.msg}') from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError('配置值必须是 JSON 对象。')
        return parsed

    def save(self, commit=True):
        config = super().save(commit=False)
        config.value = self.cleaned_data['value_text']
        if commit:
            config.save()
        return config
