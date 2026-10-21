from django.contrib import admin
from django.urls import path, include
from . import views
from account.views.login import LoginView
from app.public_reservations import (
    cancel_public_reservation,
    edit_public_reservation,
    public_reservation,
    public_reservation_detail,
    resume_public_reservation,
)
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
    path(
        "branches/<slug:slug>/reservations/new/",
        public_reservation,
        name="public-reservation",
    ),
    path(
        "reservation/continue/",
        resume_public_reservation,
        name="resume-public-reservation",
    ),
    path(
        "reservations/<int:reservation_id>/",
        public_reservation_detail,
        name="public-reservation-detail",
    ),
    path(
        "reservations/<int:reservation_id>/edit/",
        edit_public_reservation,
        name="edit-public-reservation",
    ),
    path(
        "reservations/<int:reservation_id>/cancel/",
        cancel_public_reservation,
        name="cancel-public-reservation",
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
