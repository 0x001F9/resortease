from django.contrib import admin
from django.urls import path, include
from . import views
from account.views.login import LoginView
from app.public_reservations import (
    CancelPublicReservationView,
    EditPublicReservationView,
    PublicReservationDetailView,
    PublicReservationView,
    ResumePublicReservationView,
)
from app.admin_site import admin_site

urlpatterns = [
    path("admin/", admin_site.urls, name="admin"),
    path("", views.HomeView.as_view(), name="home"),
    path("branches/", views.BranchListView.as_view(), name="branch-list"),
    path(
        "branches/<slug:slug>/",
        views.BranchDetailView.as_view(),
        name="branch-detail",
    ),
    path(
        "branches/<slug:slug>/reservations/new/",
        PublicReservationView.as_view(),
        name="public-reservation",
    ),
    path(
        "reservation/continue/",
        ResumePublicReservationView.as_view(),
        name="resume-public-reservation",
    ),
    path(
        "reservations/<int:reservation_id>/",
        PublicReservationDetailView.as_view(),
        name="public-reservation-detail",
    ),
    path(
        "reservations/<int:reservation_id>/edit/",
        EditPublicReservationView.as_view(),
        name="edit-public-reservation",
    ),
    path(
        "reservations/<int:reservation_id>/cancel/",
        CancelPublicReservationView.as_view(),
        name="cancel-public-reservation",
    ),
    path("facilities/", views.FacilityListView.as_view(), name="facility-list"),
    path(
        "facilities/<slug:slug>/",
        views.FacilityDetailView.as_view(),
        name="public-facility-detail",
    ),
    path("login/", LoginView.as_view(), name="login"),
    path("account/", include("account.urls")),
    path("dashboard/", include("dashboard.urls"))
]
