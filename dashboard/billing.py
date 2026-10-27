from decimal import Decimal, ROUND_HALF_UP

from dashboard.models.reservations import Reservation


RATE_REQUIRED_ERROR = (
    "Choose a time range matching a configured facility rate: 24 hours, "
    "22 hours, 8 AM–5 PM, or 7 PM–6 AM."
)


def calculate_total_amount(facility, starts_at, ends_at):
    return Reservation.objects.calculate_raw_amount(facility, starts_at, ends_at)


def calculate_cancellation_refund(paid_total):
    return (Decimal(paid_total) * Decimal("0.50")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
