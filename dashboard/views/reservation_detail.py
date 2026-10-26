from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Calendar, Payment, Reservation
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
        pending_payments = [
            payment
            for payment in payments
            if payment.status == Payment.Status.PENDING
        ]
        paid_total = (
            payments.filter(
                status=Payment.Status.SUCCEEDED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        pending_total = (
            payments.filter(
                status=Payment.Status.PENDING,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        total_amount = reservation.total_amount
        show_payment_info = (
            reservation.current_status == Calendar.Status.CONFIRMED
        )
        remaining_balance = (
            max(total_amount - paid_total + pending_total, Decimal("0.00"))
            if total_amount is not None and show_payment_info
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
                "pending_payments": pending_payments,
                "show_payment_info": show_payment_info,
                "total_amount": total_amount,
                "paid_total": paid_total,
                "pending_total": pending_total,
                "remaining_balance": remaining_balance,
                "is_fully_paid": (
                    total_amount is not None and remaining_balance == 0
                ),
                "completion_payment_required": (
                    request.GET.get("completion") == "payment-required"
                ),
                "hide_aside": True,
            },
        )
