import re
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from account.models import User
from dashboard.models import (
    Branch,
    Calendar,
    Facility,
    Payment,
    Reservation,
)


class PublicResortPagesTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Coastal Branch",
            slug="coastal-branch",
            city="Seabrook",
            address="1 Shore Road",
            description="A quiet coastal retreat.",
        )
        self.operational_facility = Facility.objects.create(
            branch=self.branch,
            name="Garden Pool",
            slug="garden-pool",
            status=Facility.FacilityStatus.OPERATIONAL,
            description="A quiet place to swim.",
        )
        self.closed_facility = Facility.objects.create(
            branch=self.branch,
            name="Event Pavilion",
            slug="event-pavilion",
            facility_type=Facility.FacilityType.EVENT_HALL,
            status=Facility.FacilityStatus.CLOSED,
            description="Currently closed for seasonal work.",
        )

    def test_all_public_pages_are_accessible_without_authentication(self):
        urls = (
            reverse("home"),
            reverse("branch-list"),
            reverse("branch-detail", kwargs={"slug": self.branch.slug}),
            reverse("facility-list"),
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.operational_facility.slug},
            ),
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.closed_facility.slug},
            ),
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_homepage_only_lists_operational_facilities(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, self.operational_facility.name)
        self.assertNotContains(response, self.closed_facility.name)

    def test_other_public_pages_show_non_operational_facilities(self):
        branch_response = self.client.get(
            reverse("branch-detail", kwargs={"slug": self.branch.slug})
        )
        facility_list_response = self.client.get(reverse("facility-list"))
        facility_response = self.client.get(
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.closed_facility.slug},
            )
        )

        self.assertContains(branch_response, self.closed_facility.name)
        self.assertContains(branch_response, "Closed")
        self.assertContains(facility_list_response, self.closed_facility.name)
        self.assertContains(facility_response, self.branch.name)
        self.assertContains(
            facility_response,
            "Currently closed for seasonal work.",
        )

    def test_operational_facility_detail_links_to_preselected_reservation(self):
        response = self.client.get(
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.operational_facility.slug},
            )
        )
        reservation_url = reverse(
            "public-reservation",
            kwargs={"slug": self.branch.slug},
        )

        self.assertContains(response, "Reserve this facility")
        self.assertContains(
            response,
            f'href="{reservation_url}?facility={self.operational_facility.pk}"',
        )

        closed_response = self.client.get(
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.closed_facility.slug},
            )
        )
        self.assertNotContains(closed_response, "Reserve this facility")

    def test_reservation_call_to_action_leads_to_branch_selection(self):
        response = self.client.get(reverse("home"))

        self.assertContains(
            response,
            f'href="{reverse("branch-list")}"',
        )
        self.assertContains(response, "Make a reservation")


class PublicReservationFlowTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Harbor Branch",
            slug="harbor-branch",
            city="Harbor City",
            address="1 Bay Road",
            phone_number="+15555550613",
            email="harbor@example.com",
        )
        self.facility = Facility.objects.create(
            branch=self.branch,
            name="Harbor Pool",
            slug="harbor-pool",
            rate_24hours=1000,
            capacity=4,
        )
        self.user = User.objects.create_user(
            username="reservation_guest",
            email="guest@example.com",
            password="TestPassword123!Resort",
            first_name="Harbor",
            last_name="Guest",
            phone_number_code="+1",
            phone_number="5555550610",
            email_confirmed_at=timezone.now(),
        )
        self.starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=4),
                datetime.min.time().replace(hour=9),
            )
        )
        self.payload = {
            "facility": str(self.facility.pk),
            "rate_package": "24hours",
            "starts_at": timezone.localtime(self.starts_at).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "days": "1",
            "party_size": "3",
            "special_requests": "Please prepare towels.",
        }
        self.url = reverse(
            "public-reservation",
            kwargs={"slug": self.branch.slug},
        )

    def test_get_can_preselect_requested_facility(self):
        response = self.client.get(
            self.url,
            {"facility": self.facility.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"]["facility"].value(),
            self.facility.pk,
        )

    def test_public_reservation_forms_expose_numeric_rates_to_preview(self):
        self.facility.rate_22hours = 800
        self.facility.save(update_fields=["rate_22hours", "updated_at"])

        create_response = self.client.get(self.url)
        self.assertEqual(create_response.status_code, 200)
        self.assertContains(create_response, 'data-rate24-hours="1000"')
        self.assertContains(create_response, 'data-rate22-hours="800"')

        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
        )
        edit_response = self.client.get(
            reverse(
                "edit-public-reservation",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, 'data-rate24-hours="1000"')
        self.assertContains(edit_response, 'data-rate22-hours="800"')

    def test_public_layout_exposes_configured_philippine_timezone(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["TIME_ZONE"], "Asia/Manila")
        self.assertContains(
            response,
            '<html lang="en" data-timezone="Asia/Manila">',
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_guest_sign_up_resumes_available_reservation_as_pending(self):
        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Availability confirmed")
        self.assertEqual(Reservation.objects.count(), 0)
        self.assertEqual(
            self.client.session["pending_public_reservation"]["facility"],
            str(self.facility.pk),
        )

        sign_up_response = self.client.post(
            reverse("sign-up"),
            {
                "username": "res_guest_new",
                "email": "newguest@example.com",
                "first_name": "New",
                "middle_name": "",
                "last_name": "Guest",
                "phone_number_code": "+1",
                "phone_number": "5555550611",
                "address": "2 Bay Road",
                "password1": "QwErTy!7890asDf",
                "password2": "QwErTy!7890asDf",
                "next": reverse("resume-public-reservation"),
            },
        )
        self.assertEqual(sign_up_response.status_code, 200)
        self.assertTemplateUsed(sign_up_response, "verify_email.html")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            User.objects.get(username="res_guest_new").address,
            "2 Bay Road",
        )

        verification_url = re.search(
            r"https?://testserver\S+",
            mail.outbox[0].body,
        ).group(0)
        verification_path = urlsplit(verification_url)
        verify_response = self.client.get(
            f"{verification_path.path}?{verification_path.query}"
        )

        self.assertRedirects(
            verify_response,
            reverse("resume-public-reservation"),
            fetch_redirect_response=False,
        )
        resume_response = self.client.get(reverse("resume-public-reservation"))
        self.assertRedirects(
            resume_response,
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": Reservation.objects.get().pk},
            ),
            fetch_redirect_response=False,
        )
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.guest.username, "res_guest_new")
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.party_size, 3)
        self.assertEqual(reservation.special_requests, "Please prepare towels.")
        self.assertEqual(reservation.discount, 0)
        self.assertFalse(Calendar.objects.filter(reservation=reservation).exists())
        self.assertNotIn("pending_public_reservation", self.client.session)
        detail_response = self.client.get(
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            )
        )
        self.assertContains(detail_response, "Reservation details")
        self.assertContains(detail_response, ">3</dd>")
        self.assertContains(detail_response, "first paid, first reserved")
        self.assertContains(
            detail_response,
            "Submitting a request alone does not hold the time.",
        )
        self.assertContains(detail_response, "tel:+15555550613")
        self.assertContains(detail_response, "mailto:harbor@example.com")

    def test_authenticated_request_is_pending_and_ignores_staff_fields(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                **self.payload,
                "status": Reservation.Status.CONFIRMED,
                "discount": "100",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": Reservation.objects.get().pk},
            ),
            fetch_redirect_response=False,
        )
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.party_size, 3)
        self.assertEqual(reservation.discount, 0)
        self.assertFalse(Calendar.objects.filter(reservation=reservation).exists())

    def test_public_reservation_rejects_party_size_above_facility_capacity(self):
        response = self.client.post(
            self.url,
            {**self.payload, "party_size": "5"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This facility can accommodate up to 4 guests.")
        self.assertFalse(Reservation.objects.exists())

    def test_guest_can_edit_their_pending_reservation_date(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            party_size=2,
        )
        edit_url = reverse(
            "edit-public-reservation",
            kwargs={"reservation_id": reservation.pk},
        )
        get_response = self.client.get(edit_url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'type="datetime-local"')

        new_starts_at = self.starts_at + timedelta(days=2)
        response = self.client.post(
            edit_url,
            {
                "facility": str(self.facility.pk),
                "rate_package": "24hours",
                "starts_at": timezone.localtime(new_starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "days": "1",
                "party_size": "3",
                "special_requests": "Please prepare towels.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            ),
            fetch_redirect_response=False,
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.starts_at, new_starts_at)
        self.assertEqual(reservation.ends_at, new_starts_at + timedelta(days=1))
        self.assertEqual(reservation.party_size, 3)
        self.assertEqual(reservation.special_requests, "Please prepare towels.")
        self.assertEqual(reservation.status, Reservation.Status.PENDING)

    def test_guest_can_edit_own_confirmed_upcoming_reservation_only(self):
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
        )
        edit_url = reverse(
            "edit-public-reservation",
            kwargs={"reservation_id": reservation.pk},
        )
        other_user = User.objects.create_user(
            username="reservation_editor_other",
            email="editor-other@example.com",
            password="TestPassword123!Other",
            first_name="Other",
            last_name="Editor",
            phone_number_code="+1",
            phone_number="5555550613",
            email_confirmed_at=timezone.now(),
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(edit_url).status_code, 404)

        self.client.force_login(self.user)
        reservation.status = Reservation.Status.CONFIRMED
        reservation.save(update_fields=["status", "updated_at"])
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit reservation")

        reservation.starts_at = timezone.now() - timedelta(hours=1)
        reservation.save(update_fields=["starts_at", "updated_at"])
        self.assertEqual(self.client.get(edit_url).status_code, 302)

    def test_confirmed_reservation_shows_payment_history_and_balance(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            status=Reservation.Status.CONFIRMED,
        )
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["raw_amount", "updated_at"])
        Calendar.objects.create(
            reservation=reservation,
            facility=self.facility,
            starts_at=reservation.starts_at,
            ends_at=reservation.ends_at,
            status=Calendar.Status.CONFIRMED,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Down payment",
            amount=Decimal("25.00"),
            method="cash",
            status=Payment.Status.SUCCEEDED,
            transaction_reference="public-payment-receipt",
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Balance payment",
            amount=Decimal("10.00"),
            method="bank transfer",
            status=Payment.Status.PENDING,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Cleaning fee",
            amount=Decimal("5.50"),
            method="cash",
            status=Payment.Status.PENDING,
        )

        response = self.client.get(
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Price summary")
        self.assertContains(response, "Facility reserve fees")
        self.assertContains(response, "Total paid")
        self.assertContains(response, "Total")
        self.assertContains(response, "₱ 100.00")
        self.assertContains(response, "Balance")
        self.assertContains(response, "₱ 90.50")
        self.assertNotContains(response, "Pending payments")
        self.assertContains(response, "Down payment")
        self.assertContains(response, "Balance payment")
        self.assertContains(response, "₱ 10.00")
        self.assertContains(response, "Cleaning fee")
        self.assertContains(response, "₱ 5.50")
        self.assertContains(response, "public-payment-receipt")

    def test_pending_reservation_shows_pending_payment_items(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            status=Reservation.Status.PENDING,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Pending deposit",
            amount=Decimal("35.00"),
            method="",
            status=Payment.Status.PENDING,
        )

        response = self.client.get(
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending deposit")
        self.assertContains(response, "₱ 35.00")
        self.assertNotContains(response, "Payment activity")
        self.assertNotContains(response, "Total paid")

    def test_cancelled_reservation_details_show_read_only_payment_history(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            status=Reservation.Status.CONFIRMED,
        )
        Calendar.objects.create(
            reservation=reservation,
            facility=self.facility,
            starts_at=reservation.starts_at,
            ends_at=reservation.ends_at,
            status=Calendar.Status.CANCELLED,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Down payment",
            amount=Decimal("25.00"),
            method="cash",
            status=Payment.Status.SUCCEEDED,
            transaction_reference="cancelled-reservation-receipt",
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Pending deposit",
            amount=Decimal("10.00"),
            method="cash",
            status=Payment.Status.CANCELLED,
        )

        response = self.client.get(
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment history")
        self.assertContains(response, "Down payment")
        self.assertContains(response, "Pending deposit")
        self.assertContains(response, "cancelled-reservation-receipt")
        self.assertNotContains(response, "Payment activity")
        self.assertNotContains(response, "Total paid")

    def test_settled_refund_hides_refund_contact_notice_but_keeps_payment_history(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            status=Reservation.Status.CONFIRMED,
        )
        Calendar.objects.create(
            reservation=reservation,
            facility=self.facility,
            starts_at=reservation.starts_at,
            ends_at=reservation.ends_at,
            status=Calendar.Status.CANCELLED,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Down payment",
            amount=Decimal("1200.00"),
            method="cash",
            status=Payment.Status.SUCCEEDED,
            transaction_reference="paid-reference",
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Refund",
            amount=Decimal("600.00"),
            method="cash",
            status=Payment.Status.REFUNDED,
            transaction_reference="refund-reference",
        )

        response = self.client.get(
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Arrange your refund")
        self.assertNotContains(response, "Contact Harbor Branch to arrange it.")
        self.assertNotContains(response, "1 Shore Road")
        self.assertContains(response, "Payment history")
        self.assertContains(response, "paid-reference")
        self.assertContains(response, "refund-reference")

    def test_zero_refund_hides_refund_contact_notice(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            status=Reservation.Status.CONFIRMED,
        )
        Calendar.objects.create(
            reservation=reservation,
            facility=self.facility,
            starts_at=reservation.starts_at,
            ends_at=reservation.ends_at,
            status=Calendar.Status.CANCELLED,
        )

        response = self.client.get(
            reverse(
                "public-reservation-detail",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["refund_amount"], Decimal("0.00"))
        self.assertNotContains(response, "Arrange your refund")
        self.assertNotContains(response, "1 Shore Road")
        self.assertContains(response, "Payment history")

    def test_confirmed_reservation_can_be_cancelled_with_required_reason(self):
        self.client.force_login(self.user)
        self.branch.phone_number = "+15551234567"
        self.branch.email = "coastal@example.com"
        self.branch.save(update_fields=["phone_number", "email", "updated_at"])
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
            status=Reservation.Status.CONFIRMED,
        )
        calendar_entry = Calendar.objects.create(
            reservation=reservation,
            facility=self.facility,
            starts_at=reservation.starts_at,
            ends_at=reservation.ends_at,
            status=Calendar.Status.CONFIRMED,
        )
        pending_payment = Payment.objects.create(
            reservation_id=reservation,
            name="Down payment",
            amount=Decimal("50.00"),
            method="cash",
            status=Payment.Status.PENDING,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Down payment",
            amount=Decimal("100.01"),
            method="card",
            status=Payment.Status.SUCCEEDED,
            transaction_reference="cancelled-reservation-receipt",
        )
        detail_url = reverse(
            "public-reservation-detail",
            kwargs={"reservation_id": reservation.pk},
        )
        cancel_url = reverse(
            "cancel-public-reservation",
            kwargs={"reservation_id": reservation.pk},
        )

        detail_response = self.client.get(detail_url)
        self.assertContains(detail_response, "Cancel reservation")
        self.assertContains(detail_response, "Edit reservation")
        self.assertContains(detail_response, "Why are you cancelling?")
        self.assertContains(detail_response, "50% of the amount already paid")
        self.assertContains(detail_response, "₱ 50.01")
        self.assertContains(detail_response, "tel:+15551234567")
        self.assertContains(detail_response, "mailto:coastal@example.com")

        missing_reason_response = self.client.post(cancel_url, {"reason": "  "})
        self.assertRedirects(
            missing_reason_response,
            detail_url,
            fetch_redirect_response=False,
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(calendar_entry.notes, "")

        response = self.client.post(
            cancel_url,
            {"reason": "Our travel dates changed."},
        )
        self.assertRedirects(
            response,
            detail_url,
            fetch_redirect_response=False,
        )
        reservation.refresh_from_db()
        calendar_entry.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(calendar_entry.status, Calendar.Status.CANCELLED)
        pending_payment.refresh_from_db()
        self.assertEqual(pending_payment.status, Payment.Status.CANCELLED)
        self.assertEqual(
            calendar_entry.notes,
            "Our travel dates changed.",
        )
        detail_response = self.client.get(detail_url)
        self.assertContains(detail_response, "Calendar notes")
        self.assertContains(detail_response, "Our travel dates changed.")
        self.assertContains(detail_response, "Arrange your refund")
        self.assertContains(detail_response, "₱ 50.01")
        self.assertContains(detail_response, "Contact Harbor Branch to arrange it.")
        self.assertContains(detail_response, "cancelled-reservation-receipt")
        self.assertNotContains(detail_response, "Cancel reservation")
        self.assertNotContains(detail_response, "Edit reservation")

    def test_guest_can_cancel_confirmed_in_progress_but_not_ended_reservation(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=Reservation.Status.CONFIRMED,
        )
        detail_url = reverse(
            "public-reservation-detail",
            kwargs={"reservation_id": reservation.pk},
        )
        cancel_url = reverse(
            "cancel-public-reservation",
            kwargs={"reservation_id": reservation.pk},
        )
        detail_response = self.client.get(detail_url)
        self.assertContains(detail_response, "Cancel reservation")
        self.assertNotContains(detail_response, "Edit reservation")

        reservation.ends_at = timezone.now() - timedelta(minutes=1)
        reservation.save(update_fields=["ends_at", "updated_at"])
        self.assertEqual(
            self.client.post(cancel_url, {"reason": "Plans changed."}).status_code,
            404,
        )

    def test_guest_edit_rejects_past_dates_and_unavailable_times(self):
        self.client.force_login(self.user)
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
        )
        edit_url = reverse(
            "edit-public-reservation",
            kwargs={"reservation_id": reservation.pk},
        )
        past_start = timezone.make_aware(
            datetime.combine(
                timezone.localdate() - timedelta(days=1),
                datetime.min.time().replace(hour=9),
            )
        )
        base_payload = {
            "facility": str(self.facility.pk),
            "rate_package": "24hours",
            "days": "1",
            "party_size": "2",
            "special_requests": "",
        }
        past_response = self.client.post(
            edit_url,
            {
                **base_payload,
                "starts_at": timezone.localtime(past_start).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
            },
        )
        self.assertEqual(past_response.status_code, 200)
        self.assertContains(past_response, "Reservations cannot be made for past dates.")
        reservation.refresh_from_db()
        self.assertEqual(reservation.starts_at, self.starts_at)

        blocked_start = self.starts_at + timedelta(days=2)
        Calendar.objects.create(
            facility=self.facility,
            starts_at=blocked_start,
            ends_at=blocked_start + timedelta(days=1),
        )
        conflict_response = self.client.post(
            edit_url,
            {
                **base_payload,
                "starts_at": timezone.localtime(blocked_start).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
            },
        )
        self.assertEqual(conflict_response.status_code, 200)
        self.assertContains(
            conflict_response,
            "This facility is not available during the selected time.",
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.starts_at, self.starts_at)

    def test_reservation_detail_is_only_visible_to_its_guest(self):
        reservation = Reservation.objects.create(
            guest=self.user,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
        )
        detail_url = reverse(
            "public-reservation-detail",
            kwargs={"reservation_id": reservation.pk},
        )

        anonymous_response = self.client.get(detail_url)
        self.assertRedirects(
            anonymous_response,
            f"{reverse('login')}?next={detail_url}",
            fetch_redirect_response=False,
        )

        other_user = User.objects.create_user(
            username="other_guest",
            email="other@example.com",
            password="TestPassword123!Resort",
            first_name="Other",
            last_name="Guest",
            phone_number_code="+1",
            phone_number="5555550612",
            email_confirmed_at=timezone.now(),
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_login_returns_to_a_safe_reservation_continuation(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": "TestPassword123!Resort",
                "next": reverse("resume-public-reservation"),
            },
        )

        self.assertRedirects(
            response,
            reverse("resume-public-reservation"),
            fetch_redirect_response=False,
        )

    def test_unavailable_guest_request_does_not_open_auth_prompt(self):
        Calendar.objects.create(
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(days=1),
        )

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not available")
        self.assertNotContains(response, "Availability confirmed")
        self.assertEqual(Reservation.objects.count(), 0)

    def test_public_form_labels_price_for_every_rate_option(self):
        self.facility.rate_22hours = 800
        self.facility.rate_morning = 500
        self.facility.rate_evening = 600
        self.facility.save(
            update_fields=["rate_22hours", "rate_morning", "rate_evening"]
        )

        response = self.client.get(self.url)

        for rate in ("24hours", "22hours", "morning", "evening"):
            with self.subTest(rate=rate):
                self.assertContains(response, f'data-rate-price-for="{rate}"')
        self.assertContains(response, "24-hour rate")
        self.assertContains(response, "22-hour rate")
        self.assertContains(response, "Morning rate · 8 AM–5 PM")
        self.assertContains(response, "Evening rate · 7 PM–6 AM")
        self.assertContains(response, "per day")
        self.assertContains(response, "per package")