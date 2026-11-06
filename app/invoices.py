import logging
from decimal import Decimal
from pathlib import Path
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import HttpResponse
from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from weasyprint import HTML

from dashboard.models import Payment, Reservation
from dashboard.templatetags.compact_numbers import amount_format


logger = logging.getLogger(__name__)

INVOICE_TEMPLATE_DIR = Path(settings.BASE_DIR) / "app" / "templates"
INVOICE_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(INVOICE_TEMPLATE_DIR),
    autoescape=select_autoescape(("html", "xml")),
)
INVOICE_TEMPLATE_ENV.filters["amount_format"] = amount_format


def _guest_name(guest):
    return " ".join(
        name
        for name in (guest.first_name, guest.middle_name, guest.last_name)
        if name
    ) or guest.username


def _invoice_reference(reservation):
    calendar_entry = getattr(reservation, "calendar_entry", None)
    if calendar_entry is not None and calendar_entry.booking_reference is not None:
        return str(calendar_entry.booking_reference)
    return str(reservation.pk)


def build_einvoice_context(reservation):
    payments = list(
        Payment.objects.filter(
            reservation_id=reservation,
            status__in=(Payment.Status.PENDING, Payment.Status.SUCCEEDED),
        )
        .annotate(
            status_order=Case(
                When(status=Payment.Status.PENDING, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("status_order", "created_at", "pk")
    )
    pending_total = sum(
        (
            payment.amount
            for payment in payments
            if payment.status == Payment.Status.PENDING
        ),
        Decimal("0.00"),
    )
    paid_total = sum(
        (
            payment.amount
            for payment in payments
            if payment.status == Payment.Status.SUCCEEDED
        ),
        Decimal("0.00"),
    )
    subtotal = reservation.raw_amount
    discount = reservation.discount or Decimal("0.00")
    total = reservation.total_amount
    branch = reservation.facility.branch
    guest = reservation.guest
    invoice_number = _invoice_reference(reservation)

    return {
        "invoice": {
            "number": invoice_number,
            "notes": reservation.special_requests,
        },
        "reservation_id": reservation.pk,
        "client": {
            "name": _guest_name(guest),
            "number": f"{guest.phone_number_code} {guest.phone_number}",
            "address": guest.address or "",
            "email": guest.email,
        },
        "branch": branch,
        "issue_date": timezone.localtime(timezone.now()).strftime("%B %d, %Y"),
        "party_start": timezone.localtime(reservation.starts_at).strftime(
            "%B %d, %Y %I:%M %p"
        ),
        "party_end": timezone.localtime(reservation.ends_at).strftime(
            "%B %d, %Y %I:%M %p"
        ),
        "balance": (
            max(total - paid_total, Decimal("0.00"))
            if total is not None
            else None
        ),
        "items": [
            *(
                [
                    {
                        "description": (
                            f"Facility reservation - {reservation.facility.name}"
                        ),
                        "status": "Charge",
                        "amount": subtotal,
                    }
                ]
                if subtotal is not None
                else []
            ),
            *[
                {
                    "description": payment.name,
                    "status": payment.get_status_display(),
                    "amount": payment.amount,
                }
                for payment in payments
            ],
        ],
        "totals": {
            "subtotal": subtotal,
            "discount": discount,
            "paid": paid_total,
            "pending": pending_total,
            "total": total,
        },
        "branch_address": branch.address,
    }


def render_einvoice_pdf(reservation):
    context = build_einvoice_context(reservation)
    template = INVOICE_TEMPLATE_ENV.get_template("invoice/invoice.html")
    css_path = INVOICE_TEMPLATE_DIR / "invoice" / "invoice.css"
    html = template.render(
        **context,
        css=Markup(css_path.read_text(encoding="utf-8")),
    )
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()


def einvoice_pdf_response(reservation):
    invoice_number = _invoice_reference(reservation)
    response = HttpResponse(
        render_einvoice_pdf(reservation),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="e-invoice-{invoice_number}.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    return response


def send_einvoice_email(reservation):
    pdf = render_einvoice_pdf(reservation)
    invoice_number = _invoice_reference(reservation)
    email = EmailMessage(
        subject=f"Your E-Invoice {invoice_number}",
        body=(
            f"Hello {_guest_name(reservation.guest)},\n\n"
            "Your reservation has been confirmed. Your E-Invoice is attached."
        ),
        to=[reservation.guest.email],
    )
    email.attach(f"e-invoice-{invoice_number}.pdf", pdf, "application/pdf")
    if email.send(fail_silently=False) != 1:
        raise SMTPException("The email backend did not send the E-Invoice.")


def queue_einvoice_email_on_commit(request, reservation_id):
    def send():
        try:
            reservation = Reservation.objects.select_related(
                "guest",
                "facility__branch",
            ).get(pk=reservation_id)
            send_einvoice_email(reservation)
        except (OSError, SMTPException):
            logger.exception(
                "Could not send E-Invoice for reservation %s.",
                reservation_id,
            )
            messages.error(
                request,
                "The reservation was saved, but its E-Invoice email could not be sent.",
            )

    transaction.on_commit(send)
