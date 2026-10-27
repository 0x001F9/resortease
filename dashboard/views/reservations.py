import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import CharField, Q
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.db.models.functions import Cast
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Calendar, Facility, Payment, Reservation
from dashboard.views.calendar_entries import is_day_fully_unavailable


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class ReservationsCalendarView(View):
    template_name = "reservations/index.html"

    def get(self, request, *args, **kwargs):
        now = timezone.now()
        Reservation.objects.filter(
            facility__branch=request.branch,
            status=Reservation.Status.PENDING,
            starts_at__lte=now,
        ).update(
            status=Reservation.Status.DECLINED,
            updated_at=now,
        )

        month_parameter = request.GET.get("month", "")
        try:
            calendar_month = date.fromisoformat(f"{month_parameter}-01")
        except ValueError:
            calendar_month = timezone.localdate().replace(day=1)

        next_month = (
            calendar_month.replace(day=28) + timedelta(days=4)
        ).replace(day=1)
        previous_month = calendar_month - timedelta(days=1)
        previous_month = previous_month.replace(day=1)

        reservations = Reservation.objects.filter(
            facility__branch=request.branch
        ).select_related("guest", "facility", "calendar_entry").annotate(
            booking_reference_text=Cast(
                "calendar_entry__booking_reference",
                output_field=CharField(),
            )
        )
        status_choices = [
            *Reservation.Status.choices,
            (Calendar.Status.CANCELLED, Calendar.Status.CANCELLED.label),
            (Calendar.Status.COMPLETED, Calendar.Status.COMPLETED.label),
        ]

        selected_status = request.GET.get(
            "status",
            Reservation.Status.PENDING,
        )
        valid_statuses = {value for value, _label in status_choices}
        if selected_status not in valid_statuses:
            selected_status = Reservation.Status.PENDING
        if selected_status in {
            Calendar.Status.CANCELLED,
            Calendar.Status.COMPLETED,
        }:
            reservations = reservations.filter(
                calendar_entry__status=selected_status
            )
        else:
            reservations = reservations.filter(
                Q(status=selected_status, calendar_entry__isnull=True)
                | Q(calendar_entry__status=selected_status)
            )

        search_query = request.GET.get("q", "").strip()
        if search_query:
            reservations = reservations.filter(
                Q(guest__first_name__icontains=search_query)
                | Q(guest__last_name__icontains=search_query)
                | Q(guest__username__icontains=search_query)
                | Q(guest__email__icontains=search_query)
                | Q(facility__name__icontains=search_query)
                | Q(booking_reference_text__icontains=search_query)
            )

        facilities = list(
            Facility.objects.filter(branch=request.branch).order_by("name")
        )
        selected_facility_id = request.GET.get("facility", "")
        selected_facility = next(
            (
                facility
                for facility in facilities
                if str(facility.pk) == selected_facility_id
            ),
            None,
        )
        month_start = timezone.make_aware(
            datetime.combine(calendar_month, time.min)
        )
        month_end = timezone.make_aware(
            datetime.combine(next_month, time.min)
        )
        calendar_entries = list(
            Calendar.objects.filter(
                facility__branch=request.branch,
                starts_at__lt=month_end,
                ends_at__gt=month_start,
            )
            .exclude(status=Calendar.Status.CANCELLED)
            .select_related("facility", "reservation__guest")
        )
        entries_by_day = {}
        for entry in calendar_entries:
            starts_on = max(
                timezone.localtime(entry.starts_at).date(),
                calendar_month,
            )
            ends_on = min(
                timezone.localtime(
                    entry.ends_at - timedelta(microseconds=1)
                ).date(),
                next_month - timedelta(days=1),
            )
            day = starts_on
            while day <= ends_on:
                entries_by_day.setdefault(day, []).append(entry)
                day += timedelta(days=1)

        today = timezone.localdate()
        weeks = []
        for week in calendar.Calendar(firstweekday=0).monthdayscalendar(
            calendar_month.year, calendar_month.month
        ):
            calendar_week = []
            for day_number in week:
                if day_number:
                    day = calendar_month.replace(day=day_number)
                    day_start = timezone.make_aware(
                        datetime.combine(day, time.min)
                    )
                    day_end = timezone.make_aware(
                        datetime.combine(day + timedelta(days=1), time.min)
                    )
                    day_entries = entries_by_day.get(day, [])
                    calendar_week.append(
                        {
                            "date": day,
                            "entries": [
                                entry
                                for entry in day_entries
                                if selected_facility is None
                                or entry.facility_id == selected_facility.pk
                            ],
                            "is_today": day == today,
                            "is_unavailable": is_day_fully_unavailable(
                                day_entries,
                                facilities,
                                day_start,
                                day_end,
                                selected_facility,
                            ),
                        }
                    )
                else:
                    calendar_week.append(None)
            weeks.append(calendar_week)

        branch_reservations = Reservation.objects.filter(
            facility__branch=request.branch
        )
        total_bookings = Calendar.objects.filter(
            facility__branch=request.branch,
            reservation__isnull=False,
        ).exclude(status=Calendar.Status.CANCELLED).count()
        bookings_needing_completion = (
            Calendar.objects.filter(
                facility__branch=request.branch,
                reservation__isnull=False,
                status=Calendar.Status.CONFIRMED,
                ends_at__lte=now,
            )
            .select_related("reservation__guest", "facility")
            .order_by("ends_at", "starts_at")
        )
        return render(
            request,
            self.template_name,
            {
                "reservations": reservations,
                "search_query": search_query,
                "selected_status": selected_status,
                "status_choices": status_choices,
                "calendar_month": calendar_month,
                "previous_month": previous_month,
                "next_month": next_month,
                "weeks": weeks,
                "facilities": facilities,
                "selected_facility": selected_facility,
                "total_reservations": branch_reservations.count(),
                "pending_reservations": branch_reservations.filter(
                    status=Reservation.Status.PENDING
                ).count(),
                "total_bookings": total_bookings,
                "bookings_needing_completion": bookings_needing_completion,
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class MarkBookingCompletedView(View):
    def post(self, request, entry_id, *args, **kwargs):
        now = timezone.now()
        completion_blocked = False
        reservation_id = None
        with transaction.atomic():
            entry = (
                Calendar.objects.select_for_update()
                .filter(
                    pk=entry_id,
                    facility__branch=request.branch,
                    reservation__isnull=False,
                    status=Calendar.Status.CONFIRMED,
                    ends_at__lte=now,
                )
                .first()
            )
            if entry is None:
                raise Http404("This booking cannot be marked completed.")

            reservation = Reservation.objects.select_for_update().get(
                pk=entry.reservation_id
            )
            reservation_id = reservation.pk
            total_amount = reservation.total_amount
            if total_amount is None:
                completion_blocked = True
            else:
                paid_total = (
                    reservation.payments.filter(
                        status=Payment.Status.SUCCEEDED,
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0.00")
                )
                pending_total = (
                    reservation.payments.filter(
                        status=Payment.Status.PENDING,
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0.00")
                )
                remaining_balance = max(
                    total_amount - paid_total + pending_total,
                    Decimal("0.00"),
                )
                if remaining_balance != 0:
                    completion_blocked = True

            if not completion_blocked:
                entry.status = Calendar.Status.COMPLETED
                entry.save(update_fields=["status", "updated_at"])

        if completion_blocked:
            return redirect(
                f"{reverse('reservation-detail', kwargs={'branch': request.branch.slug, 'reservation_id': reservation_id})}?completion=payment-required"
            )

        messages.success(request, "Booking marked as completed.")
        if request.POST.get("return_to") == "dashboard":
            return redirect("dashboard", branch=request.branch.slug)
        return redirect("reservations", branch=request.branch.slug)
