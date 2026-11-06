from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.billing import reservation_completion_payment_error
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.forms import ReservationEditForm
from dashboard.models import Calendar, Maintenance, Reservation
from dashboard.views.calendar_entries import has_calendar_conflict
from app.invoices import (
    queue_einvoice_email_on_commit,
)
from app.receipts import queue_ereceipt_email_on_commit


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class EditReservationView(View):
    template_name = "reservations/edit.html"

    def has_conflict(self, reservation, starts_at, ends_at):
        if reservation.facility is None:
            return False
        calendar_entry = getattr(reservation, "calendar_entry", None)
        return has_calendar_conflict(
            reservation.facility,
            starts_at,
            ends_at,
            exclude_entry_id=(
                calendar_entry.pk if calendar_entry else None
            ),
        )

    def get_form_context(self, reservation, form):
        cleaned_data = getattr(form, "cleaned_data", {})
        starts_at = cleaned_data.get("starts_at", reservation.starts_at)
        ends_at = cleaned_data.get("ends_at", reservation.ends_at)
        return {
            "reservation": reservation,
            "form": form,
            "availability_conflict": self.has_conflict(
                reservation,
                starts_at,
                ends_at,
            ),
            "facility_has_in_progress_maintenance": (
                reservation.facility is not None
                and Maintenance.objects.filter(
                    facility=reservation.facility,
                    status=Maintenance.Status.IN_PROGRESS,
                ).exists()
            ),
            "hide_aside": True,
        }

    def get_reservation(self, request, reservation_id, *, lock=False):
        reservations = Reservation.objects.select_related(
            "guest",
            "facility",
            "calendar_entry",
        )
        if lock:
            reservations = reservations.select_for_update()
        reservation = get_object_or_404(
            reservations,
            pk=reservation_id,
            facility__branch=request.branch,
        )
        return reservation

    def get(self, request, reservation_id, *args, **kwargs):
        reservation = self.get_reservation(request, reservation_id)
        if reservation is None:
            return redirect(
                "reservation-detail",
                branch=request.branch.slug,
                reservation_id=reservation_id,
            )
        form = ReservationEditForm(instance=reservation)
        if (
            request.GET.get("status") == Calendar.Status.COMPLETED
            and reservation.status == Reservation.Status.CONFIRMED
            and reservation.ends_at < timezone.now()
            and Calendar.Status.COMPLETED
            in {
                value
                for value, _label in form.fields["status"].choices
            }
        ):
            form.initial["status"] = Calendar.Status.COMPLETED
        return render(
            request,
            self.template_name,
            self.get_form_context(reservation, form),
        )

    def post(self, request, reservation_id, *args, **kwargs):
        with transaction.atomic():
            reservation = self.get_reservation(
                request,
                reservation_id,
                lock=True,
            )
            if reservation is None:
                return redirect(
                    "reservation-detail",
                    branch=request.branch.slug,
                    reservation_id=reservation_id,
                )

            original_status = reservation.status
            form = ReservationEditForm(request.POST, instance=reservation)
            if form.is_valid():
                status = form.cleaned_data["status"]
                calendar_entry = getattr(reservation, "calendar_entry", None)
                was_completed = (
                    calendar_entry is not None
                    and calendar_entry.status == Calendar.Status.COMPLETED
                )
                starts_at = form.cleaned_data["starts_at"]
                ends_at = form.cleaned_data["ends_at"]
                if self.has_conflict(
                    reservation,
                    starts_at,
                    ends_at,
                ):
                    form.add_error(
                        "ends_at",
                        "This facility already has a calendar entry during that time.",
                    )
                if (
                    original_status == Reservation.Status.CONFIRMED
                    and status == Calendar.Status.COMPLETED
                ):
                    completion_error = reservation_completion_payment_error(
                        reservation,
                        raw_amount=form.calculated_raw_amount,
                        discount=form.cleaned_data["discount"],
                    )
                    if completion_error:
                        form.add_error("status", completion_error)
                if not form.errors:
                    reservation = form.save(commit=False)
                    was_confirmed = (
                        original_status == Reservation.Status.CONFIRMED
                    )
                    if was_confirmed:
                        reservation.status = Reservation.Status.CONFIRMED
                    reservation.raw_amount = form.calculated_raw_amount
                    reservation.extra_hour_amount = (
                        form.calculated_extra_hour_amount
                    )
                    reservation.extra_hour_rate = (
                        form.calculated_extra_hour_rate
                    )
                    reservation.save()
                    if was_confirmed or status == Reservation.Status.CONFIRMED:
                        if calendar_entry is None:
                            Calendar.objects.create(
                                reservation=reservation,
                                facility=reservation.facility,
                                starts_at=reservation.starts_at,
                                ends_at=reservation.ends_at,
                                status=status,
                                notes=reservation.special_requests,
                            )
                        else:
                            calendar_entry.facility = reservation.facility
                            calendar_entry.starts_at = reservation.starts_at
                            calendar_entry.ends_at = reservation.ends_at
                            calendar_entry.status = status
                            calendar_entry.notes = reservation.special_requests
                            calendar_entry.save(
                                update_fields=[
                                    "facility",
                                    "starts_at",
                                    "ends_at",
                                    "status",
                                    "notes",
                                    "updated_at",
                                ]
                            )
                        if status == Calendar.Status.CONFIRMED:
                            Reservation.objects.decline_conflicts(reservation)
                        elif status == Calendar.Status.CANCELLED:
                            Reservation.objects.cancel_pending_payments(reservation)
                    if (
                        not was_confirmed
                        and status == Reservation.Status.CONFIRMED
                    ):
                        queue_einvoice_email_on_commit(
                            request,
                            reservation.pk,
                        )
                    if (
                        status == Calendar.Status.COMPLETED
                        and not was_completed
                    ):
                        queue_ereceipt_email_on_commit(
                            request,
                            reservation.pk,
                        )

                    return redirect(
                        reverse(
                            "reservation-detail",
                            kwargs={
                                "branch": request.branch.slug,
                                "reservation_id": reservation.pk,
                            },
                        )
                    )

        reservation.status = original_status
        return render(
            request,
            self.template_name,
            self.get_form_context(reservation, form),
        )
