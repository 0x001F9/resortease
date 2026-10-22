from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.forms import PaymentForm
from dashboard.models import Calendar, Payment, Reservation


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class CreatePaymentView(View):
    template_name = "reservations/create_payment.html"

    def get_reservation(self, request, reservation_id, *, lock=False):
        reservations = Reservation.objects.prefetch_related("payments")
        if lock:
            reservations = reservations.select_for_update()
        reservation = get_object_or_404(
            reservations,
            pk=reservation_id,
            facility__branch=request.branch,
            status=Reservation.Status.CONFIRMED,
        )
        if reservation.current_status != Calendar.Status.CONFIRMED:
            raise Http404
        return reservation

    def get_payment_context(self, reservation, form):
        paid_total = (
            reservation.payments.filter(
                status=Payment.Status.SUCCEEDED,
                currency="PHP",
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        return {
            "reservation": reservation,
            "form": form,
            "paid_total": paid_total,
            "remaining_balance": max(
                reservation.total_amount - paid_total,
                Decimal("0.00"),
            ),
            "hide_aside": True,
        }

    def get(self, request, reservation_id, *args, **kwargs):
        reservation = self.get_reservation(request, reservation_id)
        context = self.get_payment_context(
            reservation,
            PaymentForm(reservation=reservation),
        )
        if (
            reservation.total_amount is None
            or context["remaining_balance"] <= 0
        ):
            return redirect(
                reverse(
                    "reservation-detail",
                    kwargs={
                        "branch": request.branch.slug,
                        "reservation_id": reservation.pk,
                    },
                )
            )
        return render(
            request,
            self.template_name,
            context,
        )

    def post(self, request, reservation_id, *args, **kwargs):
        with transaction.atomic():
            reservation = self.get_reservation(
                request,
                reservation_id,
                lock=True,
            )
            context = self.get_payment_context(
                reservation,
                PaymentForm(reservation=reservation),
            )
            if (
                reservation.total_amount is None
                or context["remaining_balance"] <= 0
            ):
                return redirect(
                    reverse(
                        "reservation-detail",
                        kwargs={
                            "branch": request.branch.slug,
                            "reservation_id": reservation.pk,
                        },
                    )
                )

            form = PaymentForm(request.POST, reservation=reservation)
            if form.is_valid():
                payment = form.save(commit=False)
                payment.reservation_id = reservation
                payment.currency = "PHP"
                payment.status = Payment.Status.SUCCEEDED
                payment.paid_at = timezone.now()
                payment.cashier = request.user
                payment.save()
                return redirect(
                    reverse(
                        "reservation-detail",
                        kwargs={
                            "branch": request.branch.slug,
                            "reservation_id": reservation.pk,
                        },
                    )
                )

        return render(
            request,
            self.template_name,
            self.get_payment_context(reservation, form),
        )
