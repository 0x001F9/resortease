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
            status__in=(
                Reservation.Status.PENDING,
                Reservation.Status.CONFIRMED,
            ),
        )
        if reservation.current_status not in {
            Reservation.Status.PENDING,
            Calendar.Status.CONFIRMED,
        }:
            raise Http404
        return reservation

    def get_payment_context(self, reservation, form):
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
        remaining_balance = (
            max(
                reservation.total_amount - paid_total + pending_total,
                Decimal("0.00"),
            )
            if reservation.total_amount is not None
            else None
        )
        return {
            "reservation": reservation,
            "form": form,
            "paid_total": paid_total,
            "pending_total": pending_total,
            "remaining_balance": remaining_balance,
            "hide_aside": True,
        }

    def get(self, request, reservation_id, *args, **kwargs):
        reservation = self.get_reservation(request, reservation_id)
        context = self.get_payment_context(
            reservation,
            PaymentForm(
                pending_only=(
                    reservation.current_status == Reservation.Status.PENDING
                )
            ),
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
                PaymentForm(
                    pending_only=(
                        reservation.current_status == Reservation.Status.PENDING
                    )
                ),
            )
            form = PaymentForm(
                request.POST,
                pending_only=(
                    reservation.current_status == Reservation.Status.PENDING
                ),
            )
            if form.is_valid():
                payment = form.save(commit=False)
                payment.reservation_id = reservation
                payment.paid_at = (
                    timezone.now()
                    if payment.status == Payment.Status.SUCCEEDED
                    else None
                )
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


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class UpdatePendingPaymentStatusView(View):
    def post(self, request, reservation_id, payment_id, *args, **kwargs):
        with transaction.atomic():
            payment = get_object_or_404(
                Payment.objects.select_for_update(),
                pk=payment_id,
                reservation_id_id=reservation_id,
                reservation_id__facility__branch=request.branch,
                reservation_id__status=Reservation.Status.CONFIRMED,
            )
            if (
                payment.status == Payment.Status.PENDING
                and payment.reservation_id.current_status
                == Calendar.Status.CONFIRMED
            ):
                selected_status = request.POST.get("status", "")
                if selected_status in {
                    Payment.Status.SUCCEEDED,
                    Payment.Status.CANCELLED,
                }:
                    if selected_status == Payment.Status.SUCCEEDED:
                        method = request.POST.get("method", "").strip()
                        reference = request.POST.get(
                            "transaction_reference", ""
                        ).strip()
                        if (
                            method
                            and len(method) <= 50
                            and len(reference) <= 255
                        ):
                            payment.method = method
                            payment.transaction_reference = reference or None
                            payment.status = selected_status
                            payment.paid_at = timezone.now()
                            payment.save(
                                update_fields=[
                                    "method",
                                    "transaction_reference",
                                    "status",
                                    "paid_at",
                                    "updated_at",
                                ]
                            )
                    else:
                        payment.status = selected_status
                        payment.paid_at = None
                        payment.save(
                            update_fields=["status", "paid_at", "updated_at"]
                        )

        return redirect(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": request.branch.slug,
                    "reservation_id": reservation_id,
                },
            )
        )
