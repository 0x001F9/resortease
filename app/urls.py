from django.contrib import admin
from django.urls import path, include
from . import views
from account.views.login import LoginView
from app.admin_site import admin_site

urlpatterns = [
    path("admin/", admin_site.urls, name="admin"),
    path("", views.home, name="home"),
    path("branches/", views.branch_list, name="branch-list"),
    path(
        "branches/<slug:slug>/",
        views.branch_detail,
        name="branch-detail",
    ),
    path("facilities/", views.facility_list, name="facility-list"),
    path(
        "facilities/<slug:slug>/",
        views.facility_detail,
        name="public-facility-detail",
    ),
    path("login/", LoginView.as_view(), name="login"),
    path("account/", include("account.urls")),
    path("dashboard/", include("dashboard.urls"))
]
