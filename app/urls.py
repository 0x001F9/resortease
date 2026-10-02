from django.contrib import admin
from django.urls import path
from . import views
from account.views.login import LoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("login/", LoginView.as_view(), name="login"),
]
