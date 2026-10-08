from django.shortcuts import redirect, render
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from account.models import User
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Calendar, Facility, Reservation


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class CreateReservationView(View):
    template_name = "reservations/create.html"

    def get_form_context(self, request, form_data=None, errors=None):
        return {
            "facilities": Facility.objects.filter(
                branch=request.branch
            ).order_by("name"),
            "guests": User.object.filter(
                role=User.Role.User,
                is_active=True,
            ).order_by("first_name", "last_name"),
            "status_choices": Reservation.Status.choices,
            "form_data": form_data or {},
            "errors": errors or {},
        }

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            self.get_form_context(request),
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
        ends_at_value = request.POST.get("ends_at", "").strip()
        party_size_value = request.POST.get("party_size", "").strip()
        status = request.POST.get("status", Reservation.Status.PENDING)
        special_requests = request.POST.get("special_requests", "").strip()

        form_data = {
            "facility": facility_id,
            "guest": guest_id,
            "starts_at": starts_at_value,
            "ends_at": ends_at_value,
            "party_size": party_size_value,
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

        try:
            party_size = int(party_size_value)
            if party_size < 1:
                raise ValueError
        except ValueError:
            party_size = None
            errors["party_size"] = "Party size must be at least 1."

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
                party_size=party_size,
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
        return redirect("reservations", branch=request.branch.slug)
