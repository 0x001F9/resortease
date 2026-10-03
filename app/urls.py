from django.contrib import admin
from django.urls import path, include
from . import views
from account.views.login import LoginView
from app.admin_site import admin_site

urlpatterns = [
    path("admin/", admin_site.urls, name="admin"),
    path("", views.home, name="home"),
    path("login/", LoginView.as_view(), name="login"),
    path("account/", include("account.urls")),
]
