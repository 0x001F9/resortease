import calendar
from decimal import Decimal
from datetime import date, timedelta

from django.db.models import CharField, Q, Sum
from django.db.models.functions import Cast
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Calendar, Payment, Reservation


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class ReservationsCalendarView(View):
    template_name = "reservations/index.html"

    def get(self, request, *args, **kwargs):
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
        status_choices = Reservation.Status.choices

        selected_status = request.GET.get("status", "")
        valid_statuses = {value for value, _label in status_choices}
        if selected_status in valid_statuses:
            reservations = reservations.filter(status=selected_status)
        else:
            selected_status = ""

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

        calendar_entries = Calendar.objects.filter(
            facility__branch=request.branch,
            starts_at__date__lt=next_month,
            ends_at__date__gte=calendar_month,
        ).select_related("facility", "reservation__guest")
        entries_by_day = {}
        for entry in calendar_entries:
            starts_on = max(
                timezone.localtime(entry.starts_at).date(),
                calendar_month,
            )
            ends_on = min(
                timezone.localtime(entry.ends_at).date(),
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
                    calendar_week.append(
                        {
                            "date": day,
                            "entries": entries_by_day.get(day, []),
                            "is_today": day == today,
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
        ).count()
        revenue = Payment.objects.filter(
            calendar_entry__facility__branch=request.branch,
            status=Payment.Status.SUCCEEDED,
            currency="PHP",
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

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
                "total_reservations": branch_reservations.count(),
                "pending_reservations": branch_reservations.filter(
                    status=Reservation.Status.PENDING
                ).count(),
                "total_bookings": total_bookings,
                "revenue": revenue,
            },
        )
