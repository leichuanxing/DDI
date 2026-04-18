from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from .models import User, Role


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='用户名', widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': '请输入用户名'
    }))
    password = forms.CharField(label='密码', widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': '请输入密码'
    }))


class UserCreateForm(UserCreationForm):
    email = forms.EmailField(label='邮箱', required=False, widget=forms.EmailInput(attrs={
        'class': 'form-control'
    }))
    real_name = forms.CharField(label='姓名', required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    phone = forms.CharField(label='手机号', required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    department = forms.CharField(label='部门', required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    role = forms.ModelChoiceField(label='角色', queryset=Role.objects.all(), required=False, 
                                   widget=forms.Select(attrs={'class': 'form-control'}))
    
    class Meta:
        model = User
        fields = ['username', 'email', 'real_name', 'phone', 'department', 'role']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control'})
        self.fields['password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control'})


class UserEditForm(forms.ModelForm):
    new_password1 = forms.CharField(
        label='新密码',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '留空则不修改密码',
            'autocomplete': 'new-password'
        }),
        help_text='如需修改密码请填写，留空则保持原密码不变（至少8位，含字母和数字）'
    )
    new_password2 = forms.CharField(
        label='确认新密码',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '再次输入新密码',
            'autocomplete': 'new-password'
        })
    )

    class Meta:
        model = User
        fields = ['email', 'real_name', 'phone', 'department', 'role', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'real_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        pwd1 = cleaned_data.get('new_password1')
        pwd2 = cleaned_data.get('new_password2')

        # 如果只填了一个密码字段
        if pwd1 and not pwd2:
            self.add_error('new_password2', '请再次输入新密码进行确认')
        elif not pwd1 and pwd2:
            self.add_error('new_password1', '请先输入新密码')

        # 两个都填了，校验一致性和强度
        if pwd1 and pwd2:
            if pwd1 != pwd2:
                self.add_error('new_password2', '两次输入的密码不一致')
            if len(pwd1) < 8:
                self.add_error('new_password1', '密码长度不能少于8位')
            if not any(c.isalpha() for c in pwd1):
                self.add_error('new_password1', '密码必须包含至少一个字母')
            if not any(c.isdigit() for c in pwd1):
                self.add_error('new_password1', '密码必须包含至少一个数字')


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.Select(attrs={'class': 'form-control', 'choices': Role._meta.get_field('code').choices}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
