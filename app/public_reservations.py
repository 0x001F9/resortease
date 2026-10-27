from datetime import time, timedelta, timezone as datetime_timezone
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View

from app.forms import PublicReservationForm
from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.models import (
    Branch,
    Calendar,
    Facility,
    Payment,
    Reservation,
)
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


def _reservation_edit_initial(reservation):
    starts_at = reservation.starts_at
    ends_at = reservation.ends_at
    duration = ends_at.astimezone(datetime_timezone.utc) - starts_at.astimezone(
        datetime_timezone.utc
    )
    local_start = timezone.localtime(starts_at)
    local_end = timezone.localtime(ends_at)

    if duration > timedelta(0) and duration % timedelta(days=1) == timedelta(0):
        rate_package = "24hours"
        days = duration // timedelta(days=1)
    elif duration == timedelta(hours=22):
        rate_package, days = "22hours", 1
    elif (
        local_start.time() == time(8)
        and local_end.time() == time(17)
        and local_start.date() == local_end.date()
    ):
        rate_package, days = "morning", 1
    elif (
        local_start.time() == time(19)
        and local_end.time() == time(6)
        and local_end.date() == local_start.date() + timedelta(days=1)
    ):
        rate_package, days = "evening", 1
    else:
        rate_package, days = "24hours", 1

    return {
        "facility": reservation.facility_id,
        "rate_package": rate_package,
        "starts_at": local_start.strftime("%Y-%m-%dT%H:%M"),
        "days": days,
        "party_size": reservation.party_size,
        "special_requests": reservation.special_requests,
    }


class PublicReservationView(View):
    def get(self, request, slug):
        return self._handle(request, slug)

    def post(self, request, slug):
        return self._handle(request, slug)

    def _handle(self, request, slug):
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
        elif request.method == "GET":
            requested_facility_id = request.GET.get("facility", "")
            if requested_facility_id.isdecimal():
                selected_facility_id = facilities.filter(
                    pk=requested_facility_id
                ).values_list("pk", flat=True).first()
                if selected_facility_id is not None:
                    initial["facility"] = selected_facility_id

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


@method_decorator(login_required(login_url="login"), name="dispatch")
class ResumePublicReservationView(View):
    def get(self, request):
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


@method_decorator(login_required(login_url="login"), name="dispatch")
class PublicReservationDetailView(View):
    def get(self, request, reservation_id):
        reservation = get_object_or_404(
            Reservation.objects.select_related(
                "facility__branch",
                "calendar_entry",
            ),
            pk=reservation_id,
            guest=request.user,
        )
        calendar_entry = getattr(reservation, "calendar_entry", None)
        show_payment_info = reservation.current_status == Calendar.Status.CONFIRMED
        payments = reservation.payments.all() if show_payment_info else []
        pending_payments = (
            reservation.payments.filter(status=Payment.Status.PENDING)
            if reservation.current_status
            in {Reservation.Status.PENDING, Calendar.Status.CONFIRMED}
            else []
        )
        paid_total = (
            payments.filter(status=Payment.Status.SUCCEEDED).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
            if show_payment_info
            else Decimal("0.00")
        )
        pending_total = (
            payments.filter(status=Payment.Status.PENDING).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
            if show_payment_info
            else Decimal("0.00")
        )
        remaining_balance = (
            max(
                reservation.total_amount - paid_total + pending_total,
                Decimal("0.00"),
            )
            if show_payment_info and reservation.total_amount is not None
            else None
        )
        return render(
            request,
            "public/reservation_detail.html",
            {
                "reservation": reservation,
                "payments": payments,
                "pending_payments": pending_payments,
                "show_payment_info": show_payment_info,
                "paid_total": paid_total,
                "pending_total": pending_total,
                "remaining_balance": remaining_balance,
                "can_cancel": (
                    reservation.current_status == Calendar.Status.CONFIRMED
                    and reservation.ends_at > timezone.now()
                    and reservation.facility_id is not None
                ),
                "can_edit": (
                    reservation.status
                    in {Reservation.Status.PENDING, Reservation.Status.CONFIRMED}
                    and reservation.current_status
                    not in {Calendar.Status.CANCELLED, Calendar.Status.COMPLETED}
                    and reservation.starts_at > timezone.now()
                ),
                "calendar_notes": calendar_entry.notes if calendar_entry else "",
                "title": f"Reservation {reservation.pk} | ResortEase",
            },
        )


@method_decorator(login_required(login_url="login"), name="dispatch")
class EditPublicReservationView(View):
    def get(self, request, reservation_id):
        return self._handle(request, reservation_id)

    def post(self, request, reservation_id):
        return self._handle(request, reservation_id)

    def _handle(self, request, reservation_id):
        reservations = Reservation.objects.all()
        if request.method == "POST":
            reservations = reservations.select_for_update()

        with transaction.atomic():
            reservation = get_object_or_404(
                reservations,
                pk=reservation_id,
                guest=request.user,
                status__in=(
                    Reservation.Status.PENDING,
                    Reservation.Status.CONFIRMED,
                ),
            )
            if reservation.starts_at <= timezone.now():
                return redirect(
                    "public-reservation-detail",
                    reservation_id=reservation.pk,
                )
            if reservation.current_status in {
                Calendar.Status.CANCELLED,
                Calendar.Status.COMPLETED,
            }:
                return redirect(
                    "public-reservation-detail",
                    reservation_id=reservation.pk,
                )
            branch = reservation.facility.branch if reservation.facility else None
            if branch is None:
                messages.error(
                    request,
                    "This reservation can no longer be edited. Please contact the resort.",
                )
                return redirect(
                    "public-reservation-detail",
                    reservation_id=reservation.pk,
                )

            facilities = Facility.objects.filter(branch=branch).filter(
                Q(status=Facility.FacilityStatus.OPERATIONAL)
                | Q(pk=reservation.facility_id)
            ).order_by("name")
            initial = (
                None
                if request.method == "POST"
                else _reservation_edit_initial(reservation)
            )
            form = PublicReservationForm(
                request.POST if request.method == "POST" else None,
                facilities=facilities,
                initial=initial,
            )

            if request.method == "POST" and form.is_valid():
                facility = form.cleaned_data["facility"]
                starts_at = form.cleaned_data["starts_at"]
                ends_at = form.cleaned_data["ends_at"]
                raw_amount = calculate_total_amount(facility, starts_at, ends_at)
                calendar_entry = getattr(reservation, "calendar_entry", None)
                if raw_amount is None:
                    form.add_error("rate_package", RATE_REQUIRED_ERROR)
                elif has_calendar_conflict(
                    facility,
                    starts_at,
                    ends_at,
                    exclude_entry_id=(
                        calendar_entry.pk if calendar_entry else None
                    ),
                ):
                    form.add_error(
                        "starts_at",
                        "This facility is not available during the selected time.",
                    )
                else:
                    reservation.facility = facility
                    reservation.starts_at = starts_at
                    reservation.ends_at = ends_at
                    reservation.party_size = form.cleaned_data["party_size"]
                    reservation.special_requests = form.cleaned_data[
                        "special_requests"
                    ]
                    reservation.raw_amount = raw_amount
                    reservation.save(
                        update_fields=[
                            "facility",
                            "starts_at",
                            "ends_at",
                            "party_size",
                            "special_requests",
                            "raw_amount",
                            "updated_at",
                        ]
                    )
                    if calendar_entry is not None:
                        calendar_entry.facility = facility
                        calendar_entry.starts_at = starts_at
                        calendar_entry.ends_at = ends_at
                        calendar_entry.status = (
                            Calendar.Status.CONFIRMED
                            if reservation.status == Reservation.Status.CONFIRMED
                            else Calendar.Status.CANCELLED
                        )
                        calendar_entry.save(
                            update_fields=[
                                "facility",
                                "starts_at",
                                "ends_at",
                                "status",
                                "updated_at",
                            ]
                        )
                    messages.success(request, "Your reservation was updated.")
                    return redirect(
                        "public-reservation-detail",
                        reservation_id=reservation.pk,
                    )

        return render(
            request,
            "public/reservation_edit.html",
            {
                "branch": branch,
                "reservation": reservation,
                "facilities": facilities,
                "form": form,
                "title": f"Edit reservation {reservation.pk} | ResortEase",
            },
        )


@method_decorator(login_required(login_url="login"), name="dispatch")
class CancelPublicReservationView(View):
    def post(self, request, reservation_id):
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Enter a reason to cancel your reservation.")
            return redirect(
                "public-reservation-detail",
                reservation_id=reservation_id,
            )
        if len(reason) > 2000:
            messages.error(
                request,
                "The cancellation reason must be 2,000 characters or fewer.",
            )
            return redirect(
                "public-reservation-detail",
                reservation_id=reservation_id,
            )

        with transaction.atomic():
            reservation = get_object_or_404(
                Reservation.objects.select_for_update(),
                pk=reservation_id,
                guest=request.user,
                status=Reservation.Status.CONFIRMED,
                ends_at__gt=timezone.now(),
                facility__isnull=False,
            )
            calendar_entry = getattr(reservation, "calendar_entry", None)
            if (
                calendar_entry is not None
                and calendar_entry.status != Calendar.Status.CONFIRMED
            ):
                return redirect(
                    "public-reservation-detail",
                    reservation_id=reservation.pk,
                )
            if calendar_entry is None and reservation.facility is not None:
                calendar_entry = Calendar.objects.create(
                    reservation=reservation,
                    facility=reservation.facility,
                    starts_at=reservation.starts_at,
                    ends_at=reservation.ends_at,
                    status=Calendar.Status.CANCELLED,
                    notes=reason,
                )
            elif calendar_entry is not None:
                calendar_entry.status = Calendar.Status.CANCELLED
                calendar_entry.notes = reason
                calendar_entry.save(
                    update_fields=["status", "notes", "updated_at"]
                )
            Reservation.objects.cancel_pending_payments(reservation)

        messages.success(request, "Your reservation was cancelled.")
        return redirect(
            "public-reservation-detail",
            reservation_id=reservation_id,
        )
