import logging
from decimal import Decimal
from pathlib import Path
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from weasyprint import HTML

from dashboard.billing import reservation_completion_payment_error
from dashboard.models import Calendar, Payment, Reservation
from dashboard.templatetags.compact_numbers import amount_format


logger = logging.getLogger(__name__)

RECEIPT_TEMPLATE_DIR = Path(settings.BASE_DIR) / "app" / "templates"
RECEIPT_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(RECEIPT_TEMPLATE_DIR),
    autoescape=select_autoescape(("html", "xml")),
)
RECEIPT_TEMPLATE_ENV.filters["amount_format"] = amount_format


def _guest_name(guest):
    return " ".join(
        name
        for name in (guest.first_name, guest.middle_name, guest.last_name)
        if name
    ) or guest.username


def _receipt_reference(reservation):
    calendar_entry = getattr(reservation, "calendar_entry", None)
    if calendar_entry is not None and calendar_entry.booking_reference is not None:
        return str(calendar_entry.booking_reference)
    return str(reservation.pk)


def can_generate_ereceipt(reservation):
    return (
        reservation.current_status == Calendar.Status.COMPLETED
        and reservation_completion_payment_error(reservation) is None
    )


def build_ereceipt_context(reservation):
    if not can_generate_ereceipt(reservation):
        raise ValueError("An E-Receipt requires a completed, fully paid reservation.")

    payments = Payment.objects.filter(
        reservation_id=reservation,
        status=Payment.Status.SUCCEEDED,
    ).order_by("paid_at", "created_at", "pk")
    paid_total = sum(
        (payment.amount for payment in payments),
        start=Decimal("0.00"),
    )
    branch = reservation.facility.branch
    guest = reservation.guest
    return {
        "receipt_number": _receipt_reference(reservation),
        "client": {
            "name": _guest_name(guest),
            "number": f"{guest.phone_number_code} {guest.phone_number}",
            "email": guest.email,
        },
        "branch": branch,
        "facility_name": reservation.facility.name,
        "extra_hour_amount": reservation.extra_hour_amount,
        "issue_date": timezone.localtime(timezone.now()).strftime("%B %d, %Y"),
        "party_start": timezone.localtime(reservation.starts_at).strftime(
            "%B %d, %Y %I:%M %p"
        ),
        "party_end": timezone.localtime(reservation.ends_at).strftime(
            "%B %d, %Y %I:%M %p"
        ),
        "items": [
            {
                "description": payment.name,
                "method": payment.method or "—",
                "date": timezone.localtime(
                    payment.paid_at or payment.created_at
                ).strftime("%B %d, %Y %I:%M %p"),
                "amount": payment.amount,
                "reference": payment.transaction_reference,
            }
            for payment in payments
        ],
        "totals": {"paid": paid_total},
    }


def render_ereceipt_pdf(reservation):
    context = build_ereceipt_context(reservation)
    template = RECEIPT_TEMPLATE_ENV.get_template("receipt/receipt.html")
    css_path = RECEIPT_TEMPLATE_DIR / "receipt" / "receipt.css"
    html = template.render(
        **context,
        css=Markup(css_path.read_text(encoding="utf-8")),
    )
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()


def ereceipt_pdf_response(reservation):
    reference = _receipt_reference(reservation)
    response = HttpResponse(
        render_ereceipt_pdf(reservation),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="e-receipt-{reference}.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    return response


def send_ereceipt_email(reservation):
    pdf = render_ereceipt_pdf(reservation)
    reference = _receipt_reference(reservation)
    email = EmailMessage(
        subject=f"Your E-Receipt {reference}",
        body=(
            f"Hello {_guest_name(reservation.guest)},\n\n"
            "Your reservation is complete. Your E-Receipt is attached."
        ),
        to=[reservation.guest.email],
    )
    email.attach(f"e-receipt-{reference}.pdf", pdf, "application/pdf")
    if email.send(fail_silently=False) != 1:
        raise SMTPException("The email backend did not send the E-Receipt.")


def queue_ereceipt_email_on_commit(request, reservation_id):
    def send():
        try:
            reservation = Reservation.objects.select_related(
                "guest",
                "facility__branch",
                "calendar_entry",
            ).get(pk=reservation_id)
            send_ereceipt_email(reservation)
        except (OSError, SMTPException):
            logger.exception(
                "Could not send E-Receipt for reservation %s.",
                reservation_id,
            )
            messages.error(
                request,
                "The reservation was saved, but its E-Receipt email could not be sent.",
            )

    transaction.on_commit(send)
