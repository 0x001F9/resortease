from django.db import transaction
from django.db.models import QuerySet
from django.urls import reverse
from django.utils.http import urlencode
from langchain.tools import ToolRuntime, tool

from account.models import User
from app.forms import PublicReservationForm
from app.public_reservations import PENDING_RESERVATION_SESSION_KEY
from dashboard.billing import calculate_total_amount
from dashboard.models import Branch, Facility, Payment, Reservation
from dashboard.views.calendar_entries import has_calendar_conflict

from agent_chat.context import AgentContext


def _validated_request(
    branch_name: str,
    facility_name: str,
    rate_package: str,
    starts_at: str,
    party_size: int,
    special_requests: str,
    days: int,
):
    branch = Branch.objects.filter(name__iexact=branch_name.strip()).first()
    if branch is None:
        return None, "I couldn't find that branch."

    facilities = Facility.objects.filter(
        branch=branch,
        status=Facility.FacilityStatus.OPERATIONAL,
    )
    facility = facilities.filter(name__iexact=facility_name.strip()).first()
    if facility is None:
        return None, "I couldn't find an operational facility with that name."

    form = PublicReservationForm(
        data={
            "facility": str(facility.pk),
            "rate_package": rate_package,
            "starts_at": starts_at,
            "days": days,
            "party_size": party_size,
            "special_requests": special_requests,
        },
        facilities=facilities,
    )
    if not form.is_valid():
        errors = [
            str(error)
            for field_errors in form.errors.values()
            for error in field_errors
        ]
        return None, "I couldn't validate those reservation details: " + " ".join(
            errors
        )

    reservation_data = form.cleaned_data
    facility = reservation_data["facility"]
    starts_at = reservation_data["starts_at"]
    ends_at = reservation_data["ends_at"]
    rate_package = reservation_data["rate_package"]
    if calculate_total_amount(
        facility,
        starts_at,
        ends_at,
        rate_package,
    ) is None:
        return None, "That rate is not available for the selected time."
    if has_calendar_conflict(facility, starts_at, ends_at):
        return None, "That time is unavailable for this facility."

    return reservation_data, None


def auth_action_urls() -> dict[str, str]:
    chat_url = reverse("chat")
    next_query = urlencode({"next": chat_url})
    return {
        "login_url": f"{reverse('login')}?{next_query}",
        "create_account_url": f"{reverse('sign-up')}?{next_query}",
    }


@tool
def check_reservation_availability(
    branch_name: str,
    facility_name: str,
    rate_package: str,
    starts_at: str,
    party_size: int,
    special_requests: str = "",
    days: int = 1,
) -> str:
    """Check a facility reservation request and return a brief availability result.

    Args:
        branch_name: Exact name of the branch.
        facility_name: Exact facility name within that branch.
        rate_package: One of 24hours, 22hours, morning, or evening.
        starts_at: Local date and time in YYYY-MM-DDTHH:MM format.
        party_size: Number of guests expected.
        special_requests: Optional guest requests.
        days: Number of 24-hour days; ignored for other rate packages.
    """
    _, error = _validated_request(
        branch_name,
        facility_name,
        rate_package,
        starts_at,
        party_size,
        special_requests,
        days,
    )
    if error is not None:
        return f"Unavailable: {error}"
    return "Available."


@tool
def add_pending_reservation(
    branch_name: str,
    facility_name: str,
    rate_package: str,
    starts_at: str,
    party_size: int,
    special_requests: str = "",
    days: int = 1,
    *,
    runtime: ToolRuntime[AgentContext],
) -> str:
    """Create an authenticated reservation or stage it until the guest signs in.

    Args:
        branch_name: Exact name of the branch.
        facility_name: Exact facility name within that branch.
        rate_package: One of 24hours, 22hours, morning, or evening.
        starts_at: Local date and time in YYYY-MM-DDTHH:MM format.
        party_size: Number of guests expected.
        special_requests: Optional guest requests.
        days: Number of 24-hour days; ignored for other rate packages.
    """
    reservation_data, error = _validated_request(
        branch_name,
        facility_name,
        rate_package,
        starts_at,
        party_size,
        special_requests,
        days,
    )
    if error is not None:
        return f"I couldn't create that reservation request. {error}"

    facility = reservation_data["facility"]
    if runtime.context.user_id is not None:
        guest = User.objects.filter(pk=runtime.context.user_id).first()
        if guest is None:
            raise RuntimeError("The authenticated chat user could not be found.")
        with transaction.atomic():
            User.objects.select_for_update().get(pk=guest.pk)
            if Reservation.objects.has_guest_time_conflict(
                guest,
                reservation_data["starts_at"],
                reservation_data["ends_at"],
            ):
                return (
                    "I couldn't create that reservation request. You already have "
                    "a reservation that overlaps this time."
                )
            Reservation.objects.create(
                guest=guest,
                facility=facility,
                starts_at=reservation_data["starts_at"],
                ends_at=reservation_data["ends_at"],
                rate_package=reservation_data["rate_package"],
                party_size=reservation_data["party_size"],
                special_requests=reservation_data["special_requests"],
                status=Reservation.Status.PENDING,
            )
        return "Your reservation request was saved to your account and is pending confirmation."

    runtime.context.session[PENDING_RESERVATION_SESSION_KEY] = {
        "branch_id": facility.branch_id,
        "facility": str(facility.pk),
        "rate_package": reservation_data["rate_package"],
        "starts_at": reservation_data["starts_at"].strftime("%Y-%m-%dT%H:%M"),
        "days": reservation_data["days"],
        "party_size": reservation_data["party_size"],
        "special_requests": reservation_data["special_requests"],
    }
    runtime.context.session.save()
    runtime.context.requires_auth_actions = True
    return (
        "Your reservation request is ready. Sign in or create an account to save it; "
        "it will be saved automatically when you return to chat."
    )


@tool
def get_latest_reservation(
    runtime: ToolRuntime[AgentContext],
) -> dict | str:
    """Fetch the authenticated guest's latest reservation and payment list."""
    user_id = runtime.context.user_id
    if user_id is None:
        runtime.context.requires_auth_actions = True
        return "Please sign in or create an account to view your latest reservation."

    reservation = (
        Reservation.objects.filter(guest_id=user_id)
        .select_related("facility", "calendar_entry")
        .prefetch_related("payments")
        .order_by("-created_at")
        .first()
    )
    if reservation is None:
        return "You don't have any reservations yet."

    payments: QuerySet[Payment] = reservation.payments.all()
    return {
        "facility": (
            reservation.facility.name if reservation.facility is not None else None
        ),
        "date_and_time": {
            "starts_at": reservation.starts_at.isoformat(),
            "ends_at": reservation.ends_at.isoformat(),
        },
        "party_size": reservation.party_size,
        "special_requests": reservation.special_requests,
        "status": reservation.current_status_display,
        "amount": (
            str(reservation.total_amount)
            if reservation.total_amount is not None
            else None
        ),
        "payments": [
            {
                "name": payment.name,
                "amount": str(payment.amount),
                "method": payment.method,
                "status": payment.get_status_display(),
                "paid_at": (
                    payment.paid_at.isoformat() if payment.paid_at is not None else None
                ),
            }
            for payment in payments
        ],
    }
