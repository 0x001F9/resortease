from django.contrib import admin
from django.contrib.auth import get_user_model
from django.shortcuts import redirect

class SuperUserAdmin(admin.AdminSite):
    def has_permission(self, request):
        return request.user.is_authenticated and request.user.is_superuser

    def login(self, request, extra_context=None):
        return redirect("/login/")

admin_site = SuperUserAdmin(name='admin')

for model, model_admin in admin.site._registry.items():
    admin_site.register(model, model_admin.__class__)

admin_site.register(get_user_model())