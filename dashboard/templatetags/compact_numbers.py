from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def compact_number(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    if not number.is_finite():
        return value

    absolute = abs(number)
    suffixes = (
        (Decimal("1000000000000"), "T"),
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
        (Decimal("1000"), "K"),
    )

    for threshold, suffix in suffixes:
        if absolute >= threshold:
            scaled = number / threshold
            formatted = format(scaled, ".2f").rstrip("0").rstrip(".")
            return f"{formatted}{suffix}"

    return format(number, ".2f")


@register.filter
def amount_format(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    if not number.is_finite():
        return value

    return format(number, ",.2f")
