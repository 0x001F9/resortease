from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from account.models import User


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
