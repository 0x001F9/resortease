from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from dashboard.models.reservations import Payment, Reservation


RATE_REQUIRED_ERROR = (
    "Choose a time range matching the selected facility rate. Time beyond the "
    "included package must be in full-hour increments and requires a configured "
    "extra-hour rate."
)


def calculate_total_amount(facility, starts_at, ends_at, rate_package=None):
    return Reservation.objects.calculate_raw_amount(
        facility,
        starts_at,
        ends_at,
        rate_package,
    )


def calculate_extra_hour_amount(facility, starts_at, ends_at, rate_package):
    return Reservation.objects.calculate_extra_hour_amount(
        facility,
        starts_at,
        ends_at,
        rate_package,
    )


def calculate_cancellation_refund(paid_total):
    return (Decimal(paid_total) * Decimal("0.50")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def reservation_completion_payment_error(
    reservation,
    *,
    raw_amount=None,
    discount=None,
):
    if raw_amount is None:
        raw_amount = reservation.raw_amount
    if discount is None:
        discount = reservation.discount
    if raw_amount is None:
        return "Set a reservation amount before marking this booking completed."
    raw_amount = Decimal(str(raw_amount))
    discount = Decimal(str(discount or "0.00"))
    total_amount = max(raw_amount - discount, Decimal("0.00"))

    totals = reservation.payments.aggregate(
        paid=Sum(
            "amount",
            filter=Q(status=Payment.Status.SUCCEEDED),
        ),
        pending=Sum(
            "amount",
            filter=Q(status=Payment.Status.PENDING),
        ),
    )
    remaining_balance = max(
        total_amount
        - (totals["paid"] or Decimal("0.00"))
        + (totals["pending"] or Decimal("0.00")),
        Decimal("0.00"),
    )
    if remaining_balance:
        return (
            "The booking cannot be completed until its balance is paid. "
            f"Remaining balance: ₱{remaining_balance:.2f}."
        )
    return None
