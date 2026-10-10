from datetime import time, timedelta, timezone as datetime_timezone
from decimal import Decimal

from django.utils import timezone


RATE_REQUIRED_ERROR = (
    "Choose a time range matching a configured facility rate: 24 hours, "
    "22 hours, 8 AM–5 PM, or 7 PM–6 AM."
)


def calculate_total_amount(facility, starts_at, ends_at):
    duration = ends_at.astimezone(datetime_timezone.utc) - starts_at.astimezone(
        datetime_timezone.utc
    )
    rate = None

    if duration == timedelta(hours=24):
        rate = facility.rate_24hours
    elif duration == timedelta(hours=22):
        rate = facility.rate_22hours
    else:
        local_start = timezone.localtime(starts_at)
        local_end = timezone.localtime(ends_at)
        if (
            local_start.time() == time(8)
            and local_end.time() == time(17)
            and local_start.date() == local_end.date()
        ):
            rate = facility.rate_morning
        elif (
            local_start.time() == time(19)
            and local_end.time() == time(6)
            and local_end.date() == local_start.date() + timedelta(days=1)
        ):
            rate = facility.rate_evening

    return Decimal(rate) if rate is not None else None
