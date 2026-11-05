from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, Permission

from account.forms import AdminUserChangeForm, AdminUserCreationForm
from account.models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    model = User
    list_display = (
        "username",
        "email",
        "role",
        "assigned_branch",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "assigned_branch", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "middle_name",
                    "last_name",
                    "email",
                    "phone_number_code",
                    "phone_number",
                    "avatar_url",
                    "role",
                    "assigned_branch",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        ("Account security", {"fields": ("email_confirmed_at", "totp_enabled")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "phone_number_code",
                    "phone_number",
                    "role",
                    "assigned_branch",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    readonly_fields = ("last_login", "created_at", "updated_at")


for auth_model in (Group, Permission):
    if admin.site.is_registered(auth_model):
        admin.site.unregister(auth_model)
