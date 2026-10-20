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
            "address",
        )
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "input w-full"}),
            "middle_name": forms.TextInput(attrs={"class": "input w-full"}),
            "last_name": forms.TextInput(attrs={"class": "input w-full"}),
            "phone_number_code": forms.TextInput(attrs={"class": "input w-full"}),
            "phone_number": forms.TextInput(attrs={"class": "input w-full"}),
            "address": forms.Textarea(attrs={"class": "textarea w-full", "rows": 3}),
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
            "address",
            "role",
            "is_active",
            "is_staff",
            "is_superuser",
        )


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class SignUpForm(UserCreationForm):
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "input w-full"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "input w-full"}),
    )

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
            "address",
        )
        widgets = {
            "username": forms.TextInput(
                attrs={"class": "input w-full", "autocomplete": "username"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "input w-full", "autocomplete": "email"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "input w-full", "autocomplete": "given-name"}
            ),
            "middle_name": forms.TextInput(
                attrs={"class": "input w-full", "autocomplete": "additional-name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "input w-full", "autocomplete": "family-name"}
            ),
            "phone_number_code": forms.TextInput(
                attrs={
                    "class": "input w-full",
                    "placeholder": "+63",
                    "autocomplete": "tel-country-code",
                }
            ),
            "phone_number": forms.TextInput(
                attrs={"class": "input w-full", "autocomplete": "tel-national"}
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "textarea w-full",
                    "rows": 3,
                    "autocomplete": "street-address",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].required = True
