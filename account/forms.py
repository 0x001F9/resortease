from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from account.models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "first_name",
            "middle_name",
            "last_name",
            "phone_number_code",
            "phone_number",
        )
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "input w-full"}),
            "middle_name": forms.TextInput(attrs={"class": "input w-full"}),
            "last_name": forms.TextInput(attrs={"class": "input w-full"}),
            "phone_number_code": forms.TextInput(attrs={"class": "input w-full"}),
            "phone_number": forms.TextInput(attrs={"class": "input w-full"}),
        }


class AdminUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "middle_name",
            "last_name",
            "phone_number_code",
            "phone_number",
            "role",
            "is_active",
            "is_staff",
            "is_superuser",
        )


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
