from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

# 注册用的表单
class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
    
    def clean_email(self):
        """验证邮箱唯一性"""
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exists():
            raise ValidationError('该邮箱已被注册，请使用其他邮箱或尝试找回密码。')
        return email

# 对于登录表单，Django 自带的 AuthenticationForm 已经足够使用，无需额外定义。