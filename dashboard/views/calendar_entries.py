from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from account.models import User
from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Calendar, Facility, Reservation


def get_entries_for_day(branch, selected_day, facility=None):
    day_start = timezone.make_aware(datetime.combine(selected_day, time.min))
    day_end = timezone.make_aware(
        datetime.combine(selected_day + timedelta(days=1), time.min)
    )
    entries = Calendar.objects.filter(
        facility__branch=branch,
        starts_at__lt=day_end,
        ends_at__gt=day_start,
    ).exclude(status=Calendar.Status.CANCELLED)
    if facility is not None:
        entries = entries.filter(facility=facility)
    return entries.select_related(
        "facility", "reservation__guest"
    ).order_by("starts_at")


def has_calendar_conflict(facility, starts_at, ends_at, exclude_entry_id=None):
    entries = Calendar.objects.filter(
        facility=facility,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exclude(status=Calendar.Status.CANCELLED)
    if exclude_entry_id is not None:
        entries = entries.exclude(pk=exclude_entry_id)
    return entries.exists()


def is_day_fully_unavailable(
    entries,
    facilities,
    day_start,
    day_end,
    facility=None,
):
    facility_ids = (
        [facility.pk]
        if facility is not None
        else [current_facility.pk for current_facility in facilities]
    )
    fully_blocked = set()
    for facility_id in facility_ids:
        intervals = sorted(
            (
                max(entry.starts_at, day_start),
                min(entry.ends_at, day_end),
            )
            for entry in entries
            if entry.is_unavailable
            and entry.facility_id == facility_id
            and entry.starts_at < day_end
            and entry.ends_at > day_start
        )
        covered_until = day_start
        for interval_start, interval_end in intervals:
            if interval_start > covered_until:
                break
            covered_until = max(covered_until, interval_end)
            if covered_until >= day_end:
                fully_blocked.add(facility_id)
                break
    if facility is not None:
        return facility.pk in fully_blocked
    return bool(facility_ids) and len(fully_blocked) == len(facility_ids)


def is_past_date(selected_day):
    return selected_day < timezone.localdate()


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class CalendarDayEntriesView(View):
    def get(self, request, *args, **kwargs):
        try:
            selected_day = date.fromisoformat(request.GET.get("date", ""))
        except ValueError:
            return HttpResponseBadRequest("A valid calendar date is required.")

        facilities = list(
            Facility.objects.filter(branch=request.branch).order_by("name")
        )
        facility_id = request.GET.get("facility", "")
        selected_facility = next(
            (
                facility
                for facility in facilities
                if str(facility.pk) == facility_id
            ),
            None,
        )
        if facility_id and selected_facility is None:
            return HttpResponseBadRequest("A valid facility is required.")

        day_start = timezone.make_aware(
            datetime.combine(selected_day, time.min)
        )
        day_end = timezone.make_aware(
            datetime.combine(selected_day + timedelta(days=1), time.min)
        )
        all_entries = get_entries_for_day(request.branch, selected_day)
        is_unavailable = is_day_fully_unavailable(
            all_entries,
            facilities,
            day_start,
            day_end,
            selected_facility,
        )
        return render(
            request,
            "reservations/partials/calendar_day_entries.html",
            {
                "selected_day": selected_day,
                "entries": (
                    [
                        entry
                        for entry in all_entries
                        if selected_facility is None
                        or entry.facility_id == selected_facility.pk
                    ]
                ),
                "selected_facility": selected_facility,
                "is_unavailable": is_unavailable,
                "is_past_date": is_past_date(selected_day),
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class CreateUnavailableView(View):
    template_name = "reservations/create_unavailable.html"

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
        date_value = (
            request.GET.get("date", "")
            or form_data.get("selected_date", "")
            or form_data.get("starts_at", "")[:10]
        )
        try:
            selected_day = date.fromisoformat(date_value)
        except ValueError:
            selected_day = None
        return {
            "facilities": facilities,
            "selected_facility": selected_facility,
            "form_data": form_data,
            "errors": errors or {},
            "selected_day": selected_day,
            "selected_date": (
                selected_day.isoformat()
                if selected_day
                else form_data.get("starts_at", "")[:10]
            ),
            "availability_type": form_data.get(
                "availability_type", "specific_hours"
            ),
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
        try:
            selected_day = date.fromisoformat(selected_date)
        except ValueError:
            form_data = {}
        else:
            form_data = {
                "starts_at": f"{selected_day.isoformat()}T09:00",
                "ends_at": f"{selected_day.isoformat()}T10:00",
                "availability_type": "specific_hours",
            }
        return render(
            request,
            self.template_name,
            self.get_form_context(request, form_data),
        )

    def post(self, request, *args, **kwargs):
        facility_id = request.POST.get("facility", "").strip()
        starts_at_value = request.POST.get("starts_at", "").strip()
        ends_at_value = request.POST.get("ends_at", "").strip()
        selected_date_value = request.POST.get("selected_date", "").strip()
        availability_type = request.POST.get(
            "availability_type", "specific_hours"
        )
        form_data = {
            "facility": facility_id,
            "starts_at": starts_at_value,
            "ends_at": ends_at_value,
            "selected_date": selected_date_value,
            "availability_type": availability_type,
        }
        errors = {}

        facility = (
            Facility.objects.filter(
                pk=facility_id,
                branch=request.branch,
            ).first()
            if facility_id.isdecimal()
            else None
        )
        if facility is None:
            errors["facility"] = "Select a facility in this branch."

        starts_at = None
        ends_at = None
        if availability_type not in {"whole_day", "specific_hours"}:
            errors["availability_type"] = "Select a valid unavailable-time option."
        elif availability_type == "whole_day":
            day_value = selected_date_value or starts_at_value[:10]
            try:
                selected_day = date.fromisoformat(day_value)
            except ValueError:
                errors["selected_date"] = "Enter a valid date."
            else:
                starts_at = timezone.make_aware(
                    datetime.combine(selected_day, time.min)
                )
                ends_at = timezone.make_aware(
                    datetime.combine(selected_day + timedelta(days=1), time.min)
                )
                form_data["starts_at"] = f"{selected_day.isoformat()}T00:00"
                form_data["ends_at"] = (
                    f"{(selected_day + timedelta(days=1)).isoformat()}T00:00"
                )
                form_data["selected_date"] = selected_day.isoformat()
        else:
            starts_at = parse_datetime(starts_at_value)
            ends_at = parse_datetime(ends_at_value)
            if starts_at is None:
                errors["starts_at"] = "Enter a valid start date and time."
            elif timezone.is_naive(starts_at):
                starts_at = timezone.make_aware(starts_at)

            if ends_at is None:
                errors["ends_at"] = "Enter a valid end date and time."
            elif timezone.is_naive(ends_at):
                ends_at = timezone.make_aware(ends_at)

        if starts_at is not None and ends_at is not None and ends_at <= starts_at:
            errors["ends_at"] = "The end date and time must be after the start."
        if (
            starts_at is not None
            and timezone.localtime(starts_at).date() < timezone.localdate()
        ):
            errors["starts_at"] = "Entries cannot be added to a past date."
        if (
            facility is not None
            and starts_at is not None
            and ends_at is not None
            and ends_at > starts_at
            and has_calendar_conflict(facility, starts_at, ends_at)
        ):
            errors["starts_at"] = (
                "This facility already has an entry during that time."
            )

        if errors:
            return render(
                request,
                self.template_name,
                self.get_form_context(request, form_data, errors),
            )

        with transaction.atomic():
            Calendar.objects.create(
                facility=facility,
                starts_at=starts_at,
                ends_at=ends_at,
            )

        reservations_url = reverse(
            "reservations",
            kwargs={"branch": request.branch.slug},
        )
        return redirect(
            f"{reservations_url}?month={timezone.localtime(starts_at).strftime('%Y-%m')}"
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class EditCalendarEntryView(View):
    template_name = "reservations/edit_calendar_entry.html"

    def get_entry(self, request, entry_id):
        return get_object_or_404(
            Calendar.objects.select_related(
                "facility", "reservation__guest"
            ),
            pk=entry_id,
            facility__branch=request.branch,
        )

    def get_form_context(self, request, entry, form_data=None, errors=None):
        form_data = form_data or {}
        reservation = entry.reservation if entry.reservation_id else None
        guests = list(
            User.object.filter(
                role=User.Role.User,
                is_active=True,
            ).order_by("first_name", "last_name")
        )
        if reservation and reservation.guest not in guests:
            guests.append(reservation.guest)
        return {
            "entry": entry,
            "reservation": reservation,
            "facilities": Facility.objects.filter(
                branch=request.branch
            ).order_by("name"),
            "guests": guests,
            "status_choices": Reservation.Status.choices,
            "form_data": form_data or {
                "facility": str(entry.facility_id),
                "starts_at": timezone.localtime(entry.starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "ends_at": timezone.localtime(entry.ends_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "guest": str(reservation.guest_id) if reservation else "",
                "status": reservation.status if reservation else "",
                "party_size": reservation.party_size if reservation else 1,
                "special_requests": (
                    reservation.special_requests if reservation else ""
                ),
            },
            "errors": errors or {},
            "hide_aside": True,
        }

    def get(self, request, entry_id, *args, **kwargs):
        entry = self.get_entry(request, entry_id)
        if entry.status == Calendar.Status.CANCELLED:
            return redirect("reservations", branch=request.branch.slug)
        return render(
            request,
            self.template_name,
            self.get_form_context(request, entry),
        )

    def post(self, request, entry_id, *args, **kwargs):
        entry = self.get_entry(request, entry_id)
        if entry.status == Calendar.Status.CANCELLED:
            return redirect("reservations", branch=request.branch.slug)

        facility_id = request.POST.get("facility", "").strip()
        starts_at_value = request.POST.get("starts_at", "").strip()
        ends_at_value = request.POST.get("ends_at", "").strip()
        form_data = {
            "facility": facility_id,
            "starts_at": starts_at_value,
            "ends_at": ends_at_value,
        }
        errors = {}

        facility = (
            Facility.objects.filter(
                pk=facility_id,
                branch=request.branch,
            ).first()
            if facility_id.isdecimal()
            else None
        )
        if facility is None:
            errors["facility"] = "Select a facility in this branch."

        starts_at = parse_datetime(starts_at_value)
        ends_at = parse_datetime(ends_at_value)
        if starts_at is None:
            errors["starts_at"] = "Enter a valid start date and time."
        elif timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at)
        if ends_at is None:
            errors["ends_at"] = "Enter a valid end date and time."
        elif timezone.is_naive(ends_at):
            ends_at = timezone.make_aware(ends_at)
        if starts_at is not None and ends_at is not None and ends_at <= starts_at:
            errors["ends_at"] = "The end date and time must be after the start."

        reservation = entry.reservation if entry.reservation_id else None
        guest = None
        status = ""
        party_size = 1
        special_requests = ""
        if reservation:
            guest_id = request.POST.get("guest", "")
            guest = (
                User.object.filter(
                    pk=guest_id,
                    role=User.Role.User,
                ).first()
                if guest_id.isdecimal()
                else None
            )
            if guest is None:
                errors["guest"] = "Select a valid guest."
            status = request.POST.get("status", "")
            if status not in Reservation.Status.values:
                errors["status"] = "Select a valid reservation status."
            try:
                party_size = int(request.POST.get("party_size", ""))
                if party_size < 1:
                    raise ValueError
            except ValueError:
                errors["party_size"] = "Party size must be at least 1."
            special_requests = request.POST.get(
                "special_requests", ""
            ).strip()
            form_data.update(
                {
                    "guest": request.POST.get("guest", ""),
                    "status": status,
                    "party_size": request.POST.get("party_size", ""),
                    "special_requests": special_requests,
                }
            )

        raw_amount = None
        if (
            reservation is not None
            and facility is not None
            and starts_at is not None
            and ends_at is not None
            and ends_at > starts_at
        ):
            raw_amount = calculate_total_amount(
                facility, starts_at, ends_at
            )
            if raw_amount is None:
                errors["starts_at"] = RATE_REQUIRED_ERROR

        if (
            facility is not None
            and starts_at is not None
            and ends_at is not None
            and ends_at > starts_at
            and (
                reservation is None
                or (
                    raw_amount is not None
                    and status
                    in {
                        Reservation.Status.CONFIRMED,
                        Reservation.Status.COMPLETED,
                    }
                )
            )
            and has_calendar_conflict(
                facility,
                starts_at,
                ends_at,
                exclude_entry_id=entry.pk,
            )
        ):
            errors["starts_at"] = (
                "This facility already has an entry during that time."
            )

        if errors:
            return render(
                request,
                self.template_name,
                self.get_form_context(request, entry, form_data, errors),
            )

        with transaction.atomic():
            entry.facility = facility
            entry.starts_at = starts_at
            entry.ends_at = ends_at
            if reservation:
                reservation.guest = guest
                reservation.facility = facility
                reservation.starts_at = starts_at
                reservation.ends_at = ends_at
                reservation.raw_amount = raw_amount
                reservation.status = status
                reservation.party_size = party_size
                reservation.special_requests = special_requests
                reservation.save()
                if status == Reservation.Status.CANCELLED:
                    entry.status = Calendar.Status.CANCELLED
                elif status == Reservation.Status.COMPLETED:
                    entry.status = Calendar.Status.COMPLETED
                elif status == Reservation.Status.CONFIRMED:
                    entry.status = Calendar.Status.CONFIRMED
                else:
                    entry.status = Calendar.Status.CANCELLED
            entry.save()

        reservations_url = reverse(
            "reservations",
            kwargs={"branch": request.branch.slug},
        )
        return redirect(
            f"{reservations_url}?month={timezone.localtime(starts_at).strftime('%Y-%m')}"
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class RemoveCalendarEntryView(View):
    def post(self, request, entry_id, *args, **kwargs):
        with transaction.atomic():
            entry = get_object_or_404(
                Calendar.objects.select_related("reservation"),
                pk=entry_id,
                facility__branch=request.branch,
            )
            if entry.reservation_id is not None:
                reservation = entry.reservation
                reservation.status = Reservation.Status.CANCELLED
                reservation.save(update_fields=["status", "updated_at"])
                entry.status = Calendar.Status.CANCELLED
                entry.save(update_fields=["status", "updated_at"])
            else:
                entry.delete()

        reservations_url = reverse(
            "reservations",
            kwargs={"branch": request.branch.slug},
        )
        return redirect(
            f"{reservations_url}?month={timezone.localtime(entry.starts_at).strftime('%Y-%m')}"
        )
