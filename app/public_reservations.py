from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from app.forms import PublicReservationForm
from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.models import Branch, Facility, Reservation
from dashboard.views.calendar_entries import has_calendar_conflict


PENDING_RESERVATION_SESSION_KEY = "pending_public_reservation"


def _public_facilities(branch):
    return Facility.objects.filter(
        branch=branch,
        status=Facility.FacilityStatus.OPERATIONAL,
    ).order_by("name")


def _reservation_context(request, branch, form, auth_modal=False):
    return {
        "branch": branch,
        "facilities": _public_facilities(branch),
        "form": form,
        "auth_modal": auth_modal,
        "login_url": (
            f"{reverse('login')}?next={reverse('resume-public-reservation')}"
        ),
        "signup_url": (
            f"{reverse('sign-up')}?next={reverse('resume-public-reservation')}"
        ),
        "title": f"Reserve at {branch.name} | ResortEase",
    }


def public_reservation(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    facilities = _public_facilities(branch)
    pending = request.session.get(PENDING_RESERVATION_SESSION_KEY, {})
    initial = {}
    if pending.get("branch_id") == branch.pk:
        initial = {
            key: pending[key]
            for key in (
                "facility",
                "rate_package",
                "starts_at",
                "days",
                "party_size",
                "special_requests",
            )
            if key in pending
        }

    form = PublicReservationForm(
        request.POST or None,
        facilities=facilities,
        initial=initial if request.method == "GET" else None,
    )
    auth_modal = False
    if request.method == "POST" and form.is_valid():
        facility = form.cleaned_data["facility"]
        starts_at = form.cleaned_data["starts_at"]
        ends_at = form.cleaned_data["ends_at"]
        raw_amount = calculate_total_amount(facility, starts_at, ends_at)
        if raw_amount is None:
            form.add_error("rate_package", RATE_REQUIRED_ERROR)
        elif has_calendar_conflict(facility, starts_at, ends_at):
            form.add_error(
                "starts_at",
                "This facility is not available during the selected time.",
            )
        elif request.user.is_authenticated:
            reservation = Reservation.objects.create(
                guest=request.user,
                facility=facility,
                starts_at=starts_at,
                ends_at=ends_at,
                party_size=form.cleaned_data["party_size"],
                status=Reservation.Status.PENDING,
                special_requests=form.cleaned_data["special_requests"],
            )
            messages.success(
                request,
                "Your reservation request was submitted and is pending confirmation.",
            )
            return redirect(
                "public-reservation-detail",
                reservation_id=reservation.pk,
            )
        else:
            request.session[PENDING_RESERVATION_SESSION_KEY] = {
                "branch_id": branch.pk,
                "facility": str(facility.pk),
                "rate_package": form.cleaned_data["rate_package"],
                "starts_at": timezone.localtime(starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "days": form.cleaned_data["days"],
                "party_size": form.cleaned_data["party_size"],
                "special_requests": form.cleaned_data["special_requests"],
            }
            auth_modal = True

    return render(
        request,
        "public/reservation_create.html",
        _reservation_context(request, branch, form, auth_modal),
    )


@login_required(login_url="login")
def resume_public_reservation(request):
    pending = request.session.get(PENDING_RESERVATION_SESSION_KEY)
    if not pending:
        messages.info(request, "There is no reservation request to continue.")
        return redirect("branch-list")

    branch = get_object_or_404(Branch, pk=pending.get("branch_id"))
    facilities = _public_facilities(branch)
    form = PublicReservationForm(data=pending, facilities=facilities)
    if not form.is_valid():
        request.session.pop(PENDING_RESERVATION_SESSION_KEY, None)
        messages.error(
            request,
            "Your saved reservation details are no longer valid. Please start again.",
        )
        return redirect("public-reservation", slug=branch.slug)

    facility = form.cleaned_data["facility"]
    starts_at = form.cleaned_data["starts_at"]
    ends_at = form.cleaned_data["ends_at"]
    if calculate_total_amount(facility, starts_at, ends_at) is None:
        messages.error(
            request,
            "The selected rate is no longer available. Please choose another time.",
        )
        return redirect("public-reservation", slug=branch.slug)
    if has_calendar_conflict(facility, starts_at, ends_at):
        messages.error(
            request,
            "Availability has changed. Please choose another time.",
        )
        return redirect("public-reservation", slug=branch.slug)

    reservation = Reservation.objects.create(
        guest=request.user,
        facility=facility,
        starts_at=starts_at,
        ends_at=ends_at,
        party_size=form.cleaned_data["party_size"],
        status=Reservation.Status.PENDING,
        special_requests=form.cleaned_data["special_requests"],
    )
    request.session.pop(PENDING_RESERVATION_SESSION_KEY, None)
    messages.success(
        request,
        "Your reservation request was submitted and is pending confirmation.",
    )
    return redirect(
        "public-reservation-detail",
        reservation_id=reservation.pk,
    )


@login_required(login_url="login")
def public_reservation_detail(request, reservation_id):
    reservation = get_object_or_404(
        Reservation.objects.select_related("facility__branch"),
        pk=reservation_id,
        guest=request.user,
    )
    return render(
        request,
        "public/reservation_detail.html",
        {
            "reservation": reservation,
            "title": f"Reservation {reservation.pk} | ResortEase",
        },
    )
