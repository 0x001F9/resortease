from datetime import date, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation

from django.shortcuts import redirect, render
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from account.models import User
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.models import Calendar, Facility, Reservation
from dashboard.views.calendar_entries import (
    get_entries_for_day,
    has_calendar_conflict,
    is_past_date,
)

RATE_PACKAGE_DURATIONS = {
    "22hours": timedelta(hours=22),
    "morning": timedelta(hours=9),
    "evening": timedelta(hours=11),
}


def get_package_end(rate_package, starts_at, days):
    if rate_package == "24hours":
        duration = timedelta(days=days)
    elif rate_package in RATE_PACKAGE_DURATIONS:
        duration = RATE_PACKAGE_DURATIONS[rate_package]
    else:
        return None

    if (
        rate_package == "morning"
        and timezone.localtime(starts_at).time() != time(8)
    ):
        return None
    if (
        rate_package == "evening"
        and timezone.localtime(starts_at).time() != time(19)
    ):
        return None

    end_utc = starts_at.astimezone(datetime_timezone.utc) + duration
    return end_utc.astimezone(starts_at.tzinfo)


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class CreateReservationView(View):
    template_name = "reservations/create.html"
    auto_confirm = False

    def get_form_context(self, request, form_data=None, errors=None):
        form_data = form_data or {}
        facilities = Facility.objects.filter(branch=request.branch).order_by(
            "name"
        )
        selected_facility_id = request.GET.get("facility") or form_data.get(
            "facility", ""
        )
        selected_facility = (
            facilities.filter(pk=selected_facility_id).first()
            if selected_facility_id.isdecimal()
            else None
        )
        if selected_facility is not None:
            form_data.setdefault("facility", str(selected_facility.pk))
        date_value = request.GET.get("date", "") or form_data.get(
            "starts_at", ""
        )[:10]
        try:
            selected_day = date.fromisoformat(date_value)
        except ValueError:
            selected_day = None
        return {
            "facilities": facilities,
            "guests": User.object.filter(
                role=User.Role.User,
                is_active=True,
            ).order_by("first_name", "last_name"),
            "status_choices": Reservation.Status.choices,
            "form_data": form_data or {},
            "errors": errors or {},
            "selected_day": selected_day,
            "selected_facility": selected_facility,
            "is_past_date": (
                is_past_date(selected_day) if selected_day else False
            ),
            "date_entries": (
                get_entries_for_day(
                    request.branch, selected_day, selected_facility
                )
                if selected_day
                else []
            ),
            "hide_aside": True,
        }

    def get(self, request, *args, **kwargs):
        selected_date = request.GET.get("date", "")
        initial_form_data = {}
        try:
            selected_day = date.fromisoformat(selected_date)
        except ValueError:
            pass
        else:
            initial_form_data = {
                "starts_at": f"{selected_day.isoformat()}T09:00",
                "status": Reservation.Status.CONFIRMED,
                "days": "1",
            }
        return render(
            request,
            self.template_name,
            self.get_form_context(request, initial_form_data),
        )

    def post(self, request, *args, **kwargs):
        facilities = Facility.objects.filter(branch=request.branch)
        guests = User.object.filter(
            role=User.Role.User,
            is_active=True,
        )
        facility_id = request.POST.get("facility", "")
        guest_id = request.POST.get("guest", "")
        starts_at_value = request.POST.get("starts_at", "").strip()
        rate_package = request.POST.get("rate_package", "").strip()
        days_value = request.POST.get("days", "1").strip() or "1"
        discount_value = request.POST.get("discount", "0.00").strip() or "0.00"
        status = (
            Reservation.Status.CONFIRMED
            if self.auto_confirm
            else request.POST.get("status", Reservation.Status.PENDING)
        )
        special_requests = request.POST.get("special_requests", "").strip()

        form_data = {
            "facility": facility_id,
            "guest": guest_id,
            "starts_at": starts_at_value,
            "rate_package": rate_package,
            "days": days_value,
            "discount": discount_value,
            "status": status,
            "special_requests": special_requests,
        }
        errors = {}

        facility = (
            facilities.filter(pk=facility_id).first()
            if facility_id.isdecimal()
            else None
        )
        guest = guests.filter(pk=guest_id).first() if guest_id.isdecimal() else None

        if facility is None:
            errors["facility"] = "Select a facility in this branch."
        if guest is None:
            errors["guest"] = "Select an active guest."

        starts_at = parse_datetime(starts_at_value)
        if starts_at is None:
            errors["starts_at"] = "Enter a valid start date and time."
        elif timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at)

        if (
            starts_at is not None
            and timezone.localtime(starts_at).date() < timezone.localdate()
        ):
            errors["starts_at"] = "Reservations cannot be added to a past date."

        days = 1
        if rate_package == "24hours":
            try:
                days = int(days_value)
                if days < 1:
                    raise ValueError
            except ValueError:
                days = None
                errors["days"] = "Choose at least 1 day."
        elif rate_package not in RATE_PACKAGE_DURATIONS:
            errors["rate_package"] = "Choose a valid reservation rate."

        ends_at = (
            get_package_end(rate_package, starts_at, days)
            if starts_at is not None and days is not None
            else None
        )
        if (
            starts_at is not None
            and rate_package in {"morning", "evening"}
            and ends_at is None
        ):
            errors["starts_at"] = (
                "Morning reservations must start at 8 AM; evening reservations "
                "must start at 7 PM."
            )
        if ends_at is not None:
            form_data["ends_at"] = timezone.localtime(ends_at).strftime(
                "%Y-%m-%dT%H:%M"
            )
        else:
            form_data["ends_at"] = ""

        raw_amount = None
        if (
            facility is not None
            and starts_at is not None
            and ends_at is not None
        ):
            raw_amount = calculate_total_amount(
                facility, starts_at, ends_at
            )
            if raw_amount is None:
                errors["rate_package"] = RATE_REQUIRED_ERROR
        if (
            facility is not None
            and starts_at is not None
            and ends_at is not None
            and raw_amount is not None
            and status
            in {Reservation.Status.CONFIRMED, Reservation.Status.COMPLETED}
            and has_calendar_conflict(facility, starts_at, ends_at)
        ):
            errors["starts_at"] = (
                "This facility already has an entry during that time."
            )

        try:
            discount = Decimal(discount_value)
            if (
                not discount.is_finite()
                or discount < 0
                or discount > Decimal("99999999.99")
                or discount.quantize(Decimal("0.01")) != discount
                or (
                    raw_amount is not None
                    and discount > raw_amount
                )
            ):
                raise InvalidOperation
        except InvalidOperation:
            discount = None
            errors["discount"] = (
                "Enter a non-negative discount no greater than the raw amount, "
                "with up to 2 decimal places."
            )

        if status not in Reservation.Status.values:
            errors["status"] = "Select a valid reservation status."

        if errors:
            return render(
                request,
                self.template_name,
                self.get_form_context(request, form_data, errors),
            )

        with transaction.atomic():
            reservation = Reservation.objects.create(
                guest=guest,
                facility=facility,
                starts_at=starts_at,
                ends_at=ends_at,
                discount=discount,
                status=status,
                special_requests=special_requests,
            )
            if status in {
                Reservation.Status.CONFIRMED,
                Reservation.Status.COMPLETED,
            }:
                calendar_status = (
                    Calendar.Status.COMPLETED
                    if status == Reservation.Status.COMPLETED
                    else Calendar.Status.CONFIRMED
                )
                Calendar.objects.create(
                    reservation=reservation,
                    facility=facility,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status=calendar_status,
                )
        reservations_url = reverse(
            "reservations",
            kwargs={"branch": request.branch.slug},
        )
        return redirect(
            f"{reservations_url}?month={timezone.localtime(starts_at).strftime('%Y-%m')}"
        )


class CreateBookingView(CreateReservationView):
    template_name = "reservations/create_booking.html"
    auto_confirm = True
