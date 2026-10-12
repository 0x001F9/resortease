from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Payment, Reservation
from dashboard.views.calendar_entries import has_calendar_conflict


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class ReservationDetailView(View):
    template_name = "reservations/detail.html"

    def get(self, request, reservation_id, *args, **kwargs):
        reservation = get_object_or_404(
            Reservation.objects.select_related(
                "guest",
                "facility",
                "calendar_entry__facility",
            ).prefetch_related("payments"),
            pk=reservation_id,
            facility__branch=request.branch,
        )
        payments = reservation.payments.all()
        paid_total = (
            payments.filter(
                status=Payment.Status.SUCCEEDED,
                currency="PHP",
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        total_amount = reservation.total_amount
        remaining_balance = (
            max(total_amount - paid_total, Decimal("0.00"))
            if total_amount is not None
            else None
        )
        calendar_entry = getattr(reservation, "calendar_entry", None)
        availability_conflict = (
            reservation.facility is not None
            and has_calendar_conflict(
                reservation.facility,
                reservation.starts_at,
                reservation.ends_at,
                exclude_entry_id=(
                    calendar_entry.pk if calendar_entry else None
                ),
            )
        )
        return render(
            request,
            self.template_name,
            {
                "reservation": reservation,
                "calendar_entry": calendar_entry,
                "availability_conflict": availability_conflict,
                "payments": payments,
                "paid_total": paid_total,
                "remaining_balance": remaining_balance,
                "is_fully_paid": (
                    total_amount is not None and paid_total >= total_amount
                ),
                "hide_aside": True,
            },
        )
