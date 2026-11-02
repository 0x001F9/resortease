from account.admin import CustomUserAdmin
from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.shortcuts import redirect


class SuperUserAdmin(admin.AdminSite):
    def has_permission(self, request):
        return request.user.is_authenticated and request.user.role != request.user.Role.User and request.user.is_superuser

    def login(self, request, extra_context=None):
        return redirect("/login/")


admin_site = SuperUserAdmin(name="admin")
user_model = get_user_model()

for model, default_model_admin in admin.site._registry.items():
    if model is user_model:
        continue
    admin_site.register(model, default_model_admin.__class__)

admin_site.register(user_model, CustomUserAdmin)

for model in apps.get_models():
    if not admin_site.is_registered(model):
        admin_site.register(model)