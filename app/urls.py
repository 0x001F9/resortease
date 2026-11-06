from django.contrib import admin
from django.urls import path, include
from . import views
from account.views.login import LoginView
from app.public_reservations import (
    CancelPublicReservationView,
    EditPublicReservationView,
    PublicReservationDetailView,
    PublicReservationEInvoiceDownloadView,
    PublicReservationEReceiptDownloadView,
    PublicReservationView,
    ResumePublicReservationView,
)
from app.admin_site import admin_site
from app.theme import THEME_COOKIE_NAME, valid_theme, with_theme
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme


@require_POST
@with_theme
def change_theme(request):
    theme = valid_theme(request.POST.get("theme"))
    next_url = request.POST.get("next") or request.headers.get("Referer") or "/"
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = "/"
    response = redirect(next_url)
    response.set_cookie(
        THEME_COOKIE_NAME,
        theme,
        max_age=60 * 60 * 24 * 365,
        samesite="Lax",
    )
    return response

urlpatterns = [
    path("theme/change/", change_theme, name="change-theme"),
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
        "reservations/<int:reservation_id>/einvoice/",
        PublicReservationEInvoiceDownloadView.as_view(),
        name="public-reservation-einvoice",
    ),
    path(
        "reservations/<int:reservation_id>/ereceipt/",
        PublicReservationEReceiptDownloadView.as_view(),
        name="public-reservation-ereceipt",
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
    path("dashboard/", include("dashboard.urls")),
    path("chat/", include("agent_chat.urls")),
]
