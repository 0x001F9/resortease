from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import User
from dashboard.models import (
    Branch,
    Calendar,
    Facility,
    Inventory,
    InventoryAsset,
    InventoryTransaction,
    Maintenance,
    Payment,
    Reservation,
)
from dashboard.models.inventory_assets import InventoryAssetHistory


class CalendarEntryViewTests(TestCase):
    def setUp(self):
        self.user = User.object.create(
            username="calendarstaff",
            role=User.Role.Employee,
            phone_number_code="+1",
            phone_number="5551234567",
            email="calendarstaff@example.com",
            first_name="Calendar",
            last_name="Staff",
            is_superuser=True,
            is_active=True,
        )
        self.client.force_login(self.user)
        self.branch = Branch.objects.create(
            name="Test Branch",
            slug="test-branch",
            city="Test City",
            address="1 Test Street",
        )
        self.facility = Facility.objects.create(
            branch=self.branch,
            name="Test Pool",
            slug="test-pool",
        )

    def create_unavailable(self, facility, selected_day, starts_at, ends_at):
        day_start = datetime.combine(selected_day, time.min)
        Calendar.objects.create(
            facility=facility,
            starts_at=timezone.make_aware(day_start + starts_at),
            ends_at=timezone.make_aware(day_start + ends_at),
        )

    def create_calendar_reservation(self, starts_at, ends_at):
        guest = User.object.create(
            username="booking_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234570",
            email="booking_guest@example.com",
            first_name="Booking",
            last_name="Guest",
        )
        reservation = Reservation.objects.create(
            guest=guest,
            facility=self.facility,
            starts_at=starts_at,
            ends_at=ends_at,
            status=Reservation.Status.CONFIRMED,
        )
        entry = Calendar.objects.create(
            reservation=reservation,
            facility=self.facility,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        return reservation, entry

    def get_calendar_day(self, response, selected_day):
        return next(
            day
            for week in response.context["weeks"]
            for day in week
            if day is not None and day["date"] == selected_day
        )

    def test_maintenance_issue_type_suggests_resort_issues_and_accepts_custom_values(self):
        add_url = f"/dashboard/{self.branch.slug}/add-maintenance/"
        add_response = self.client.get(add_url)

        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, 'list="maintenance-issue-types"')
        self.assertContains(add_response, 'value="Plumbing"')
        self.assertContains(add_response, 'value="Pool / Spa"')

        response = self.client.post(
            add_url,
            {
                "facility": str(self.facility.pk),
                "title": "Replace room television",
                "issue_type": "Guest room television",
                "priority": Maintenance.Priority.MEDIUM,
                "description": "Television does not turn on.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Maintenance.objects.filter(issue_type="Guest room television").exists()
        )

        maintenance = Maintenance.objects.get(issue_type="Guest room television")
        edit_response = self.client.get(
            reverse(
                "edit-maintenance",
                kwargs={
                    "branch": self.branch.slug,
                    "maintenance_id": maintenance.pk,
                },
            )
        )

        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, 'list="maintenance-issue-types"')
        self.assertContains(edit_response, 'value="Plumbing"')
        self.assertContains(edit_response, 'value="Guest room television"')

    def test_maintenance_main_table_filters_statuses_and_history_shows_all(self):
        status_titles = {
            Maintenance.Status.PENDING: "Pending",
            Maintenance.Status.IN_PROGRESS: "In progress",
            Maintenance.Status.COMPLETED: "Completed",
            Maintenance.Status.CANCELLED: "Cancelled",
        }
        maintenance_by_status = {}
        for status in Maintenance.Status.values:
            maintenance_by_status[status] = Maintenance.objects.create(
                facility=self.facility,
                title=f"{status_titles[status]} maintenance",
                issue_type="Pool / Spa",
                priority=(
                    Maintenance.Priority.URGENT
                    if status == Maintenance.Status.PENDING
                    else Maintenance.Priority.HIGH
                ),
                status=status,
                description=f"Test request in {status} status.",
                issued_by=self.user,
            )

        main_response = self.client.get(
            reverse(
                "facilities-and-maintenance",
                kwargs={"branch": self.branch.slug},
            )
        )

        self.assertEqual(main_response.status_code, 200)
        main_statuses = {
            issue.status for issue in main_response.context["maintenance"]
        }
        self.assertEqual(
            main_statuses,
            {Maintenance.Status.PENDING, Maintenance.Status.CANCELLED},
        )
        self.assertNotContains(main_response, "In progress maintenance")
        self.assertNotContains(main_response, "Completed maintenance")
        self.assertContains(main_response, 'class="bg-error/20"')
        self.assertContains(main_response, 'class="bg-warning/30"')

        history_response = self.client.get(
            reverse(
                "maintenance-history",
                kwargs={"branch": self.branch.slug},
            )
        )

        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(
            set(history_response.context["maintenance"]),
            set(maintenance_by_status.values()),
        )
        history_html = history_response.content.decode()
        for status in (
            Maintenance.Status.IN_PROGRESS,
            Maintenance.Status.COMPLETED,
        ):
            row_start = history_html.index(f"{status_titles[status]} maintenance")
            row_start = history_html.rfind("<tr", 0, row_start)
            row_open_end = history_html.index(">", row_start)
            self.assertNotIn("class=", history_html[row_start:row_open_end])
        for status in Maintenance.Status.values:
            with self.subTest(status=status):
                self.assertContains(
                    history_response,
                    f"{status_titles[status]} maintenance",
                )

    def test_marking_maintenance_completed_sets_completed_timestamp(self):
        maintenance = Maintenance.objects.create(
            facility=self.facility,
            title="Repair pool pump",
            issue_type="Pool / Spa",
            priority=Maintenance.Priority.HIGH,
            status=Maintenance.Status.PENDING,
            description="Pump is not circulating water.",
            issued_by=self.user,
        )
        edit_url = reverse(
            "edit-maintenance",
            kwargs={
                "branch": self.branch.slug,
                "maintenance_id": maintenance.pk,
            },
        )
        edit_form_response = self.client.get(edit_url)
        self.assertContains(edit_form_response, 'name="status"')
        self.assertNotContains(edit_form_response, "Current status")
        self.assertEqual(
            edit_form_response.content.decode().count('name="status"'),
            1,
        )

        response = self.client.post(
            edit_url,
            {
                "facility": str(self.facility.pk),
                "title": maintenance.title,
                "issue_type": maintenance.issue_type,
                "description": maintenance.description,
                "priority": Maintenance.Priority.HIGH,
                "status": Maintenance.Status.COMPLETED,
            },
        )

        self.assertEqual(response.status_code, 302)
        maintenance.refresh_from_db()
        self.assertEqual(maintenance.status, Maintenance.Status.COMPLETED)
        self.assertIsNotNone(maintenance.completed_at)

        edit_completed_response = self.client.get(edit_url)
        self.assertContains(edit_completed_response, 'name="status"')
        self.assertNotContains(edit_completed_response, "Current status")

        detail_response = self.client.get(
            reverse(
                "maintenance-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "maintenance_id": maintenance.pk,
                },
            )
        )
        self.assertContains(detail_response, "Completed")
        self.assertNotContains(detail_response, "Not completed")

    def test_reservation_list_defaults_to_pending_without_all_status_option(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=9),
            )
        )
        for index, status in enumerate(
            (Reservation.Status.PENDING, Reservation.Status.CONFIRMED)
        ):
            guest = User.object.create(
                username=f"status_guest_{index}",
                role=User.Role.User,
                phone_number_code="+1",
                phone_number=f"555123458{index}",
                email=f"status_guest_{index}@example.com",
                first_name="Status",
                last_name="Guest",
            )
            Reservation.objects.create(
                guest=guest,
                facility=self.facility,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                status=status,
            )

        url = reverse("reservations", kwargs={"branch": self.branch.slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_status"],
            Reservation.Status.PENDING,
        )
        self.assertEqual(
            list(
                response.context["reservations"].values_list(
                    "status", flat=True
                )
            ),
            [Reservation.Status.PENDING],
        )
        self.assertNotContains(response, "All statuses")

        confirmed_response = self.client.get(
            url,
            {"status": Reservation.Status.CONFIRMED},
        )
        self.assertEqual(
            confirmed_response.context["selected_status"],
            Reservation.Status.CONFIRMED,
        )
        self.assertEqual(
            list(
                confirmed_response.context["reservations"].values_list(
                    "status", flat=True
                )
            ),
            [Reservation.Status.CONFIRMED],
        )

    def test_calendar_day_dialog_shows_overlapping_entries(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        Calendar.objects.create(
            facility=self.facility,
            starts_at=timezone.make_aware(
                datetime.combine(selected_day - timedelta(days=1), datetime.min.time())
                + timedelta(hours=23)
            ),
            ends_at=timezone.make_aware(
                datetime.combine(selected_day, datetime.min.time())
                + timedelta(hours=2)
            ),
        )

        response = self.client.get(
            reverse(
                "calendar-day-entries",
                kwargs={"branch": self.branch.slug},
            ),
            {"date": selected_day.isoformat()},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unavailable")
        self.assertContains(response, "Test Pool")
        self.assertNotContains(response, "No entries are scheduled")
        self.assertContains(response, "Create booking")

    def test_calendar_day_dialog_shows_empty_state(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        response = self.client.get(
            reverse(
                "calendar-day-entries",
                kwargs={"branch": self.branch.slug},
            ),
            {"date": selected_day.isoformat()},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No entries are scheduled for this date.")

    def test_past_date_dialog_does_not_offer_add_actions(self):
        selected_day = timezone.localdate() - timedelta(days=1)
        response = self.client.get(
            reverse(
                "calendar-day-entries",
                kwargs={"branch": self.branch.slug},
            ),
            {"date": selected_day.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Past dates are read-only.")
        self.assertNotContains(response, "Create booking")
        self.assertNotContains(response, "Add unavailable time")

    def test_reservation_form_prefills_selected_date(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        Calendar.objects.create(
            facility=self.facility,
            starts_at=timezone.make_aware(
                datetime.combine(selected_day, datetime.min.time())
                + timedelta(hours=11)
            ),
            ends_at=timezone.make_aware(
                datetime.combine(selected_day, datetime.min.time())
                + timedelta(hours=12)
            ),
        )
        response = self.client.get(
            reverse(
                "create-reservation",
                kwargs={"branch": self.branch.slug},
            ),
            {"date": selected_day.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{selected_day.isoformat()}T09:00"')
        self.assertContains(response, 'type="datetime-local"')
        self.assertContains(response, 'lang="en-US"')
        self.assertRegex(
            response.content.decode(),
            r'data-start-picker[^>]*\sdisabled(?:\s|>)',
        )
        self.assertContains(response, 'name="rate_package"')
        self.assertContains(response, 'name="days"')
        self.assertContains(
            response,
            'class="form-control w-full sm:col-span-2"',
        )
        self.assertContains(response, 'type="hidden" name="ends_at"')
        self.assertContains(response, "data-end-display")
        self.assertContains(response, ">Ends</span>")
        self.assertContains(response, 'class="input input-bordered flex w-full items-center"')
        self.assertNotContains(response, "data-start-display")
        self.assertNotContains(response, 'type="datetime-local" name="ends_at"')
        self.assertLess(
            response.content.index(b'data-start-picker'),
            response.content.index(b'data-end-display'),
        )
        self.assertContains(response, "Price summary")
        self.assertContains(response, "/static/js/reservation-price-preview.js")
        self.assertContains(response, 'name="party_size"')
        self.assertContains(response, '<option value="confirmed" selected>')
        self.assertContains(
            response,
            f"Entries for {selected_day.strftime('%A, %B')} {selected_day.day}",
        )
        self.assertContains(response, "Unavailable")

    def test_calendar_booking_form_is_short_and_automatically_confirmed(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        response = self.client.get(
            reverse(
                "create-booking",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "date": selected_day.isoformat(),
                "facility": str(self.facility.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create booking")
        self.assertContains(response, "automatically confirmed")
        self.assertContains(response, f'value="{selected_day.isoformat()}T09:00"')
        self.assertContains(response, 'lang="en-US"')
        self.assertContains(response, 'type="datetime-local"')
        self.assertContains(response, 'name="rate_package"')
        self.assertContains(response, 'name="days"')
        self.assertContains(response, 'data-start-picker')
        self.assertRegex(
            response.content.decode(),
            r'data-start-picker[^>]*\sdisabled(?:\s|>)',
        )
        self.assertContains(response, 'type="hidden" name="ends_at"')
        self.assertContains(response, "data-end-display")
        self.assertContains(response, ">Ends</span>")
        self.assertContains(response, 'class="input input-bordered flex w-full items-center"')
        self.assertNotContains(response, "data-start-display")
        self.assertNotContains(response, 'type="datetime-local" name="ends_at"')
        self.assertLess(
            response.content.index(b'data-start-picker'),
            response.content.index(b'data-end-display'),
        )
        self.assertContains(
            response,
            f'value="{self.facility.pk}" data-rate-24-hours=""',
        )
        self.assertContains(response, "Price summary")
        self.assertContains(response, "/static/js/reservation-price-preview.js")
        self.assertContains(response, 'name="party_size"')
        self.assertNotContains(response, "special_requests")
        self.assertNotContains(response, "name=\"status\"")

    def test_guest_search_includes_active_users_of_every_role(self):
        worker = User.object.create(
            username="frontdesk_mira",
            role=User.Role.FrontDeskAgent,
            phone_number_code="+1",
            phone_number="5551234590",
            email="mira.guest@example.com",
            first_name="Mira",
            middle_name="Fern",
            last_name="Guest",
        )
        inactive_worker = User.object.create(
            username="inactive_mira",
            role=User.Role.Employee,
            phone_number_code="+1",
            phone_number="5551234591",
            email="inactive.mira@example.com",
            first_name="Mira",
            last_name="Inactive",
            is_active=False,
        )
        url = reverse(
            "search-reservation-guests",
            kwargs={"branch": self.branch.slug},
        )

        for query in ("mira fern", "frontdesk_mira", "mira.guest@example.com"):
            with self.subTest(query=query):
                response = self.client.get(url, {"q": query})
                self.assertEqual(response.status_code, 200)
                result_ids = [
                    result["id"] for result in response.json()["results"]
                ]
                self.assertIn(worker.pk, result_ids)
                self.assertNotIn(inactive_worker.pk, result_ids)

    def test_reservation_and_booking_forms_use_guest_search_modal(self):
        for route_name in ("create-reservation", "create-booking"):
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(route_name, kwargs={"branch": self.branch.slug})
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Find a guest")
                self.assertContains(response, "reservation-user-picker.js")
                self.assertNotContains(response, '<select name="guest"')
                if route_name == "create-reservation":
                    self.assertNotContains(response, 'name="status"')

    def test_calendar_booking_is_confirmed_and_added_to_calendar(self):
        self.facility.rate_morning = 90
        self.facility.save()
        guest = User.object.create(
            username="direct_booking_guest",
            role=User.Role.Employee,
            phone_number_code="+1",
            phone_number="5551234571",
            email="direct_booking_guest@example.com",
            first_name="Direct",
            last_name="Booking",
        )
        starts_at = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            reverse(
                "create-booking",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "guest": str(guest.pk),
                "starts_at": f"{starts_at.isoformat()}T08:00",
                "rate_package": "morning",
                "status": Reservation.Status.PENDING,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('reservations', kwargs={'branch': self.branch.slug})}"
            f"?month={starts_at.strftime('%Y-%m')}",
        )
        reservation = Reservation.objects.get(guest=guest)
        calendar_entry = Calendar.objects.get(reservation=reservation)
        self.assertEqual(reservation.party_size, 1)
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(calendar_entry.status, Calendar.Status.CONFIRMED)

    def test_reservation_detail_page_shows_booking_and_payment_details(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.special_requests = "Please prepare a quiet area."
        reservation.party_size = 3
        reservation.discount = Decimal("15.00")
        reservation.save()
        reservation.raw_amount = Decimal("120.00")
        reservation.save(update_fields=["raw_amount", "updated_at"])
        Payment.objects.create(
            reservation_id=reservation,
            type=Payment.Type.DOWNPAYMENT,
            amount=Decimal("50.00"),
            currency="PHP",
            method="cash",
            status=Payment.Status.SUCCEEDED,
            transaction_reference="receipt-123",
        )

        response = self.client.get(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Booking details")
        self.assertContains(response, "booking_guest@example.com")
        self.assertContains(response, "Test Pool")
        self.assertContains(response, "Please prepare a quiet area.")
        self.assertContains(response, "Price summary")
        self.assertContains(response, "Raw amount")
        self.assertNotContains(response, "Invoice reference")
        self.assertContains(response, "₱120.00")
        self.assertContains(response, "−₱15.00")
        self.assertContains(response, "₱105.00")
        self.assertContains(response, "Total paid: PHP 50.00")
        self.assertContains(response, "Balance: PHP 55.00")
        self.assertContains(response, "Down payment")
        self.assertContains(response, "cash")
        self.assertContains(response, "receipt-123")
        self.assertContains(response, "Edit booking")

    def test_reservation_detail_hides_payments_when_reservation_not_confirmed(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.status = Reservation.Status.PENDING
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["status", "raw_amount", "updated_at"])
        Payment.objects.create(
            reservation_id=reservation,
            amount=Decimal("20.00"),
            currency="PHP",
            method="cash",
            status=Payment.Status.SUCCEEDED,
            transaction_reference="pending-reservation-receipt",
        )

        response = self.client.get(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Payments")
        self.assertNotContains(response, "Total paid")
        self.assertNotContains(response, "pending-reservation-receipt")
        self.assertNotContains(response, "Add payment")
        self.assertContains(response, "Edit reservation")

    def test_edit_pending_reservation_updates_requests_discount_and_status(self):
        self.facility.rate_24hours = 100
        self.facility.capacity = 5
        self.facility.save(update_fields=["rate_24hours", "capacity", "updated_at"])
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        new_starts_at = starts_at + timedelta(days=2)
        reservation.status = Reservation.Status.PENDING
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["status", "raw_amount", "updated_at"])
        url = reverse(
            "edit-reservation",
            kwargs={
                "branch": self.branch.slug,
                "reservation_id": reservation.pk,
            },
        )

        response = self.client.post(
            url,
            {
                "starts_at": timezone.localtime(new_starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "ends_at": timezone.localtime(
                    new_starts_at + timedelta(hours=24)
                ).strftime("%Y-%m-%dT%H:%M"),
                "party_size": "4",
                "special_requests": "Please prepare towels.",
                "discount": "20.00",
                "status": Reservation.Status.CONFIRMED,
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            ),
        )
        reservation.refresh_from_db()
        self.assertEqual(
            reservation.special_requests,
            "Please prepare towels.",
        )
        self.assertEqual(reservation.discount, Decimal("20.00"))
        self.assertEqual(reservation.party_size, 4)
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(reservation.starts_at, new_starts_at)
        self.assertEqual(reservation.raw_amount, Decimal("100.00"))
        entry = Calendar.objects.get(reservation=reservation)
        self.assertEqual(entry.status, Calendar.Status.CONFIRMED)
        self.assertEqual(entry.starts_at, new_starts_at)
        self.assertEqual(entry.ends_at, new_starts_at + timedelta(hours=24))

    def test_edit_reservation_rejects_party_size_above_facility_capacity(self):
        self.facility.capacity = 4
        self.facility.save(update_fields=["capacity", "updated_at"])
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.status = Reservation.Status.PENDING
        reservation.save(update_fields=["status", "updated_at"])
        response = self.client.post(
            reverse(
                "edit-reservation",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            ),
            {
                "starts_at": timezone.localtime(starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "ends_at": timezone.localtime(
                    starts_at + timedelta(hours=24)
                ).strftime("%Y-%m-%dT%H:%M"),
                "party_size": "5",
                "special_requests": "",
                "discount": "0.00",
                "status": Reservation.Status.PENDING,
            },
        )

        reservation.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Party size cannot exceed the facility capacity of 4 guests.",
        )
        self.assertEqual(reservation.party_size, 1)

    def test_edit_reservation_rejects_discount_above_raw_amount(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.status = Reservation.Status.PENDING
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["status", "raw_amount", "updated_at"])

        response = self.client.post(
            reverse(
                "edit-reservation",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            ),
            {
                "starts_at": timezone.localtime(starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "ends_at": timezone.localtime(
                    starts_at + timedelta(hours=24)
                ).strftime("%Y-%m-%dT%H:%M"),
                "special_requests": "",
                "discount": "101.00",
                "status": Reservation.Status.PENDING,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Discount cannot be greater than the reservation amount.",
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.discount, Decimal("0.00"))

    def test_pending_reservation_availability_and_edit_reject_calendar_conflict(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.status = Reservation.Status.PENDING
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["status", "raw_amount", "updated_at"])
        Calendar.objects.create(
            facility=self.facility,
            starts_at=starts_at + timedelta(hours=1),
            ends_at=starts_at + timedelta(hours=2),
        )

        detail_response = self.client.get(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )
        self.assertContains(
            detail_response,
            "This facility already has a calendar entry during this reservation time.",
        )

        edit_url = reverse(
            "edit-reservation",
            kwargs={
                "branch": self.branch.slug,
                "reservation_id": reservation.pk,
            },
        )
        edit_get_response = self.client.get(edit_url)
        self.assertContains(edit_get_response, "booking_guest@example.com")
        self.assertNotContains(edit_get_response, 'name="guest"')
        self.assertContains(
            edit_get_response,
            "This facility already has a calendar entry during the selected time.",
        )

        edit_response = self.client.post(
            edit_url,
            {
                "starts_at": timezone.localtime(starts_at).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "ends_at": timezone.localtime(
                    starts_at + timedelta(hours=24)
                ).strftime("%Y-%m-%dT%H:%M"),
                "special_requests": "",
                "discount": "0.00",
                "status": Reservation.Status.PENDING,
            },
        )
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(
            edit_response,
            "This facility already has a calendar entry during that time.",
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)

    def test_confirmed_reservation_cannot_be_edited_with_reservation_form(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        response = self.client.get(
            reverse(
                "edit-reservation",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            ),
        )

    def test_add_payment_records_successful_payment_and_cashier(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["raw_amount", "updated_at"])

        response = self.client.post(
            reverse(
                "create-payment",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            ),
            {
                "amount": "35.00",
                "type": Payment.Type.DOWNPAYMENT,
                "method": "cash",
                "transaction_reference": "cashier-receipt-35",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            ),
        )
        payment = Payment.objects.get(reservation_id=reservation)
        self.assertEqual(payment.amount, Decimal("35.00"))
        self.assertEqual(payment.currency, "PHP")
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.cashier, self.user)
        self.assertIsNotNone(payment.paid_at)

        detail_response = self.client.get(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )
        self.assertContains(detail_response, "Total paid: PHP 35.00")
        self.assertContains(detail_response, "Balance: PHP 65.00")
        self.assertNotContains(detail_response, "Paid in full")
        self.assertContains(detail_response, "Add payment")

        Payment.objects.create(
            reservation_id=reservation,
            type=Payment.Type.BALANCE,
            amount=Decimal("65.00"),
            currency="PHP",
            method="cash",
            status=Payment.Status.SUCCEEDED,
        )
        fully_paid_response = self.client.get(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )
        self.assertContains(fully_paid_response, "Total paid: PHP 100.00")
        self.assertContains(fully_paid_response, "Balance: PHP 0.00")
        self.assertContains(fully_paid_response, "Paid in full")
        self.assertNotContains(fully_paid_response, "Add payment")

    def test_add_payment_rejects_amount_above_remaining_balance(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=8),
            )
        )
        reservation, _entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=24),
        )
        reservation.raw_amount = Decimal("100.00")
        reservation.save(update_fields=["raw_amount", "updated_at"])
        url = reverse(
            "create-payment",
            kwargs={
                "branch": self.branch.slug,
                "reservation_id": reservation.pk,
            },
        )

        response = self.client.post(
            url,
            {
                "amount": "100.01",
                "type": Payment.Type.FULL_PAYMENT,
                "method": "cash",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amount cannot exceed the remaining balance")
        self.assertFalse(Payment.objects.filter(reservation_id=reservation).exists())

    def test_reservation_detail_page_does_not_expose_other_branch_reservations(self):
        other_branch = Branch.objects.create(
            name="Other Branch",
            slug="other-branch",
            city="Other City",
            address="2 Test Street",
        )
        other_facility = Facility.objects.create(
            branch=other_branch,
            name="Other Pool",
            slug="other-pool",
        )
        guest = User.object.create(
            username="private_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234620",
            email="private_guest@example.com",
            first_name="Private",
            last_name="Guest",
        )
        reservation = Reservation.objects.create(
            guest=guest,
            facility=other_facility,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, hours=1),
        )

        response = self.client.get(
            reverse(
                "reservation-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "reservation_id": reservation.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_create_reservation_rejects_party_size_above_facility_capacity(self):
        self.facility.rate_24hours = 100
        self.facility.capacity = 4
        self.facility.save(update_fields=["rate_24hours", "capacity", "updated_at"])
        guest = User.object.create(
            username="capacity_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234609",
            email="capacity_guest@example.com",
            first_name="Capacity",
            last_name="Guest",
        )
        starts_at = timezone.localdate() + timedelta(days=1)

        response = self.client.post(
            reverse(
                "create-reservation",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "guest": str(guest.pk),
                "starts_at": f"{starts_at.isoformat()}T08:00",
                "rate_package": "24hours",
                "days": "1",
                "party_size": "5",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This facility can accommodate up to 4 guests.")
        self.assertFalse(Reservation.objects.exists())

    def test_created_reservations_and_bookings_store_exact_package_rates(self):
        self.facility.rate_24hours = 120
        self.facility.rate_22hours = 110
        self.facility.rate_morning = 90
        self.facility.rate_evening = 80
        self.facility.save()

        selected_day = timezone.localdate() + timedelta(days=1)
        booking_cases = (
            (
                "create-reservation",
                time(8),
                "24hours",
                2,
                Reservation.Status.PENDING,
                Decimal("240.00"),
            ),
            (
                "create-booking",
                time(8),
                "22hours",
                1,
                None,
                Decimal("110.00"),
            ),
            (
                "create-booking",
                time(8),
                "morning",
                1,
                None,
                Decimal("90.00"),
            ),
            (
                "create-booking",
                time(19),
                "evening",
                1,
                None,
                Decimal("80.00"),
            ),
        )

        for index, (
            route_name,
            start_time,
            rate_package,
            days,
            reservation_status,
            expected_amount,
        ) in enumerate(booking_cases):
            with self.subTest(route=route_name, expected_amount=expected_amount):
                starts_at = datetime.combine(
                    selected_day + timedelta(days=index * 2),
                    start_time,
                )
                guest = User.object.create(
                    username=f"priced_guest_{index}",
                    role=User.Role.User,
                    phone_number_code="+1",
                    phone_number=f"555123460{index}",
                    email=f"priced_guest_{index}@example.com",
                    first_name="Priced",
                    last_name="Guest",
                )
                post_data = {
                    "facility": str(self.facility.pk),
                    "guest": str(guest.pk),
                    "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                    "rate_package": rate_package,
                    "days": str(days),
                    "discount": "12.50",
                    "ends_at": "2099-01-01T00:00",
                }
                if route_name == "create-reservation":
                    post_data["status"] = Reservation.Status.CONFIRMED
                elif reservation_status is not None:
                    post_data["status"] = reservation_status

                response = self.client.post(
                    reverse(
                        route_name,
                        kwargs={"branch": self.branch.slug},
                    ),
                    post_data,
                )

                self.assertEqual(response.status_code, 302)
                reservation = Reservation.objects.get(guest=guest)
                self.assertEqual(
                    reservation.raw_amount,
                    expected_amount,
                )
                self.assertEqual(
                    reservation.status,
                    reservation_status or Reservation.Status.CONFIRMED,
                )
                self.assertEqual(reservation.party_size, 1)
                self.assertEqual(reservation.discount, Decimal("12.50"))
                if route_name == "create-reservation":
                    self.assertFalse(
                        Calendar.objects.filter(
                            reservation=reservation
                        ).exists()
                    )
                else:
                    calendar_entry = Calendar.objects.get(
                        reservation=reservation
                    )
                    self.assertEqual(
                        calendar_entry.status,
                        Calendar.Status.CONFIRMED,
                    )
                duration = {
                    "24hours": timedelta(days=days),
                    "22hours": timedelta(hours=22),
                    "morning": timedelta(hours=9),
                    "evening": timedelta(hours=11),
                }[rate_package]
                self.assertEqual(
                    reservation.ends_at,
                    timezone.make_aware(starts_at) + duration,
                )

    def test_reservation_discount_must_be_nonnegative_and_have_two_decimal_places(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        self.facility.rate_morning = 90
        self.facility.save()

        guest = User.object.create(
            username="discount_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234599",
            email="discount_guest@example.com",
            first_name="Discount",
            last_name="Guest",
        )
        response = self.client.post(
            reverse("create-reservation", kwargs={"branch": self.branch.slug}),
            {
                "facility": str(self.facility.pk),
                "guest": str(guest.pk),
                "starts_at": f"{selected_day.isoformat()}T08:00",
                "rate_package": "morning",
                "party_size": "1",
                "discount": "-1.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a non-negative discount")
        self.assertContains(response, 'value="-1.00"')
        self.assertFalse(Reservation.objects.filter(guest=guest).exists())

    def test_booking_requires_a_matching_package_with_a_configured_rate(self):
        self.facility.rate_24hours = 120
        self.facility.rate_22hours = 110
        self.facility.rate_morning = 90
        self.facility.rate_evening = 80
        self.facility.save()
        selected_day = timezone.localdate() + timedelta(days=1)

        cases = (
            (
                "create-booking",
                time(9),
                "morning",
                "unmatched_booking",
                None,
            ),
            (
                "create-reservation",
                time(9),
                "morning",
                "unmatched_confirmed",
                Reservation.Status.CONFIRMED,
            ),
            (
                "create-reservation",
                time(9),
                "morning",
                "unmatched_pending",
                Reservation.Status.PENDING,
            ),
            (
                "create-booking",
                time(8),
                "morning",
                "missing_rate",
                None,
            ),
        )
        for index, (
            route_name,
            start_time,
            rate_package,
            username,
            reservation_status,
        ) in enumerate(cases):
            with self.subTest(username=username):
                if username == "missing_rate":
                    self.facility.rate_morning = None
                    self.facility.save()
                guest = User.object.create(
                    username=username,
                    role=User.Role.User,
                    phone_number_code="+1",
                    phone_number=f"555123463{index}",
                    email=f"{username}@example.com",
                    first_name="Rate",
                    last_name="Required",
                )
                starts_at = datetime.combine(selected_day, start_time)

                response = self.client.post(
                    reverse(
                        route_name,
                        kwargs={"branch": self.branch.slug},
                    ),
                    {
                        "facility": str(self.facility.pk),
                        "guest": str(guest.pk),
                        "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                        "rate_package": rate_package,
                        "days": "1",
                        "party_size": "1",
                        **(
                            {"status": reservation_status}
                            if reservation_status is not None
                            else {}
                        ),
                    },
                )

                self.assertEqual(response.status_code, 200)
                error_field = (
                    "rate_package" if username == "missing_rate" else "starts_at"
                )
                self.assertIn(error_field, response.context["errors"])
                self.assertFalse(
                    Reservation.objects.filter(guest=guest).exists()
                )

    def test_calendar_booking_rejects_an_overlapping_entry(self):
        self.facility.rate_morning = 90
        self.facility.save()
        guest = User.object.create(
            username="overlap_book",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234572",
            email="overlap_booking_guest@example.com",
            first_name="Overlap",
            last_name="Guest",
        )
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=9),
            )
        )
        self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=1),
        )

        response = self.client.post(
            reverse(
                "create-booking",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "guest": str(guest.pk),
                "starts_at": f"{starts_at.date().isoformat()}T08:00",
                "rate_package": "morning",
                "party_size": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["errors"]["starts_at"],
            "This facility already has an entry during that time.",
        )
        self.assertFalse(Reservation.objects.filter(guest=guest).exists())

    def test_unavailable_block_can_be_created_from_form(self):
        starts_at = timezone.localdate() + timedelta(days=1)
        ends_at = starts_at + timedelta(days=1)
        response = self.client.post(
            reverse(
                "create-unavailable",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "starts_at": f"{starts_at.isoformat()}T23:00",
                "ends_at": f"{ends_at.isoformat()}T02:00",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('reservations', kwargs={'branch': self.branch.slug})}?month={starts_at.strftime('%Y-%m')}",
        )
        entry = Calendar.objects.get()
        self.assertTrue(entry.is_unavailable)
        self.assertEqual(entry.facility, self.facility)

    def test_unavailable_form_offers_whole_day_or_specific_hours(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        response = self.client.get(
            reverse(
                "create-unavailable",
                kwargs={"branch": self.branch.slug},
            ),
            {"date": selected_day.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="whole_day"')
        self.assertContains(response, 'value="specific_hours" checked')

    def test_whole_day_unavailability_spans_local_midnight_to_midnight(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            reverse(
                "create-unavailable",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "availability_type": "whole_day",
                "selected_date": selected_day.isoformat(),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('reservations', kwargs={'branch': self.branch.slug})}?month={selected_day.strftime('%Y-%m')}",
        )
        entry = Calendar.objects.get()
        self.assertEqual(
            timezone.localtime(entry.starts_at).date(),
            selected_day,
        )
        self.assertEqual(
            timezone.localtime(entry.starts_at).time(),
            datetime.min.time(),
        )
        self.assertEqual(
            timezone.localtime(entry.ends_at).date(),
            selected_day + timedelta(days=1),
        )
        self.assertEqual(
            timezone.localtime(entry.ends_at).time(),
            datetime.min.time(),
        )

    def test_unavailable_block_rejects_a_past_date(self):
        starts_at = timezone.localdate() - timedelta(days=1)
        response = self.client.post(
            reverse(
                "create-unavailable",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "starts_at": f"{starts_at.isoformat()}T09:00",
                "ends_at": f"{starts_at.isoformat()}T10:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Past dates are read-only.")
        self.assertFalse(Calendar.objects.exists())

    def test_unavailable_block_rejects_overlapping_entry(self):
        starts_at = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            starts_at,
            timedelta(hours=9),
            timedelta(hours=11),
        )
        response = self.client.post(
            reverse(
                "create-unavailable",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "availability_type": "specific_hours",
                "starts_at": f"{starts_at.isoformat()}T10:00",
                "ends_at": f"{starts_at.isoformat()}T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This facility already has an entry during that time.",
        )
        self.assertEqual(Calendar.objects.count(), 1)

    def test_reservation_rejects_overlapping_calendar_entry(self):
        self.facility.rate_morning = 90
        self.facility.save()
        guest = User.object.create(
            username="overlap_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234569",
            email="overlap_guest@example.com",
            first_name="Overlap",
            last_name="Guest",
        )
        starts_at = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            starts_at,
            timedelta(hours=9),
            timedelta(hours=11),
        )

        response = self.client.post(
            reverse(
                "create-reservation",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "guest": str(guest.pk),
                "starts_at": f"{starts_at.isoformat()}T08:00",
                "rate_package": "morning",
                "party_size": "1",
                "status": "confirmed",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This facility already has an entry during that time.",
        )
        self.assertEqual(Calendar.objects.count(), 1)

    def test_back_to_back_calendar_entries_do_not_conflict(self):
        starts_at = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            starts_at,
            timedelta(hours=9),
            timedelta(hours=10),
        )
        response = self.client.post(
            reverse(
                "create-unavailable",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "availability_type": "specific_hours",
                "starts_at": f"{starts_at.isoformat()}T10:00",
                "ends_at": f"{starts_at.isoformat()}T11:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Calendar.objects.count(), 2)

    def test_remove_unavailable_entry_deletes_calendar_block(self):
        starts_at = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            starts_at,
            timedelta(hours=9),
            timedelta(hours=10),
        )
        entry = Calendar.objects.get()

        response = self.client.post(
            reverse(
                "remove-calendar-entry",
                kwargs={
                    "branch": self.branch.slug,
                    "entry_id": entry.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Calendar.objects.exists())

    def test_remove_booking_cancels_reservation_and_hides_calendar_entry(self):
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=9),
            )
        )
        reservation, entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=1),
        )

        response = self.client.post(
            reverse(
                "remove-calendar-entry",
                kwargs={
                    "branch": self.branch.slug,
                    "entry_id": entry.pk,
                },
            )
        )

        reservation.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(reservation.status, Reservation.Status.CANCELLED)
        self.assertEqual(entry.status, Calendar.Status.CANCELLED)

        day_response = self.client.get(
            reverse(
                "calendar-day-entries",
                kwargs={"branch": self.branch.slug},
            ),
            {"date": timezone.localdate(starts_at).isoformat()},
        )
        self.assertContains(day_response, "No entries are scheduled")

    def test_edit_unavailable_entry_updates_facility_and_time(self):
        other_facility = Facility.objects.create(
            branch=self.branch,
            name="Test Gym",
            slug="test-gym",
        )
        starts_at = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            starts_at,
            timedelta(hours=9),
            timedelta(hours=10),
        )
        entry = Calendar.objects.get()
        updated_start = starts_at + timedelta(days=1)

        response = self.client.post(
            reverse(
                "edit-calendar-entry",
                kwargs={
                    "branch": self.branch.slug,
                    "entry_id": entry.pk,
                },
            ),
            {
                "facility": str(other_facility.pk),
                "starts_at": f"{updated_start.isoformat()}T11:00",
                "ends_at": f"{updated_start.isoformat()}T12:00",
            },
        )

        entry.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(entry.facility, other_facility)
        self.assertEqual(
            timezone.localtime(entry.starts_at).strftime("%Y-%m-%dT%H:%M"),
            f"{updated_start.isoformat()}T11:00",
        )

    def test_edit_booking_updates_reservation_and_calendar_fields(self):
        self.facility.rate_morning = 130
        self.facility.save()
        starts_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() + timedelta(days=1),
                time(hour=9),
            )
        )
        reservation, entry = self.create_calendar_reservation(
            starts_at,
            starts_at + timedelta(hours=1),
        )
        updated_start = timezone.localdate() + timedelta(days=2)
        updated_end = updated_start + timedelta(days=1)
        url = reverse(
            "edit-calendar-entry",
            kwargs={
                "branch": self.branch.slug,
                "entry_id": entry.pk,
            },
        )

        edit_response = self.client.get(url)
        self.assertContains(edit_response, "booking_guest@example.com")
        self.assertNotContains(edit_response, 'name="guest"')

        response = self.client.post(
            url,
            {
                "facility": str(self.facility.pk),
                "guest": "999999",
                "starts_at": f"{updated_start.isoformat()}T08:00",
                "ends_at": f"{updated_start.isoformat()}T17:00",
                "party_size": "3",
                "status": Reservation.Status.CONFIRMED,
                "special_requests": "Updated request",
            },
        )

        reservation.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            reservation.guest_id,
            User.object.get(username="booking_guest").pk,
        )
        self.assertEqual(reservation.party_size, 3)
        self.assertEqual(reservation.special_requests, "Updated request")
        self.assertEqual(reservation.starts_at, entry.starts_at)
        self.assertEqual(reservation.ends_at, entry.ends_at)
        self.assertEqual(
            timezone.localtime(reservation.starts_at).strftime("%Y-%m-%dT%H:%M"),
            f"{updated_start.isoformat()}T08:00",
        )
        self.assertEqual(
            timezone.localtime(reservation.ends_at).date(),
            updated_end,
        )
        self.assertEqual(reservation.raw_amount, Decimal("130.00"))

    def test_edit_booking_rejects_party_size_above_selected_facility_capacity(self):
        self.facility.capacity = 2
        self.facility.save(update_fields=["capacity", "updated_at"])
        starts_at = timezone.localdate() + timedelta(days=1)
        reservation, entry = self.create_calendar_reservation(
            timezone.make_aware(datetime.combine(starts_at, time(hour=9))),
            timezone.make_aware(datetime.combine(starts_at, time(hour=10))),
        )

        response = self.client.post(
            reverse(
                "edit-calendar-entry",
                kwargs={
                    "branch": self.branch.slug,
                    "entry_id": entry.pk,
                },
            ),
            {
                "facility": str(self.facility.pk),
                "starts_at": f"{starts_at.isoformat()}T09:00",
                "ends_at": f"{starts_at.isoformat()}T10:00",
                "party_size": "3",
                "status": Reservation.Status.CONFIRMED,
            },
        )

        reservation.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This facility can accommodate up to 2 guests.",
        )
        self.assertEqual(reservation.party_size, 1)

    def test_reservation_rejects_a_past_date(self):
        guest = User.object.create(
            username="calendar_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234568",
            email="calendar_guest@example.com",
            first_name="Calendar",
            last_name="Guest",
        )
        starts_at = timezone.localdate() - timedelta(days=1)
        response = self.client.post(
            reverse(
                "create-reservation",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "facility": str(self.facility.pk),
                "guest": str(guest.pk),
                "starts_at": f"{starts_at.isoformat()}T09:00",
                "rate_package": "24hours",
                "party_size": "1",
                "status": "confirmed",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Past dates are read-only.")
        self.assertFalse(Calendar.objects.exists())

    def test_calendar_renders_multiday_entries_on_each_overlapped_date(self):
        calendar_month = (
            timezone.localdate().replace(day=28) + timedelta(days=4)
        ).replace(day=1)
        starts_on = calendar_month.replace(day=1)
        Calendar.objects.create(
            facility=self.facility,
            starts_at=timezone.make_aware(
                datetime.combine(starts_on, datetime.min.time())
                + timedelta(hours=23)
            ),
            ends_at=timezone.make_aware(
                datetime.combine(starts_on + timedelta(days=2), datetime.min.time())
            ),
        )

        response = self.client.get(
            reverse("reservations", kwargs={"branch": self.branch.slug}),
            {"month": calendar_month.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        day_entries = {
            day["date"]: day["entries"]
            for week in response.context["weeks"]
            for day in week
            if day is not None
        }
        self.assertEqual(len(day_entries[starts_on]), 1)
        self.assertEqual(len(day_entries[starts_on + timedelta(days=1)]), 1)
        self.assertEqual(day_entries[starts_on + timedelta(days=2)], [])

    def test_full_day_unavailability_disables_selected_facility_only(self):
        other_facility = Facility.objects.create(
            branch=self.branch,
            name="Test Gym",
            slug="test-gym",
        )
        selected_day = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            selected_day,
            timedelta(),
            timedelta(days=1),
        )
        url = reverse("reservations", kwargs={"branch": self.branch.slug})

        selected_response = self.client.get(
            url,
            {
                "month": selected_day.strftime("%Y-%m"),
                "facility": self.facility.pk,
            },
        )
        all_response = self.client.get(
            url,
            {"month": selected_day.strftime("%Y-%m")},
        )

        self.assertTrue(
            self.get_calendar_day(selected_response, selected_day)[
                "is_unavailable"
            ]
        )
        self.assertTrue(self.get_calendar_day(all_response, selected_day)["entries"])
        self.assertFalse(
            self.get_calendar_day(all_response, selected_day)["is_unavailable"]
        )
        self.assertContains(selected_response, "Not available")
        self.assertNotContains(selected_response, 'aria-disabled="true"')
        self.assertNotContains(selected_response, "disabled")
        self.assertContains(all_response, other_facility.name)

        dialog_response = self.client.get(
            reverse(
                "calendar-day-entries",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "date": selected_day.isoformat(),
                "facility": str(self.facility.pk),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(dialog_response.status_code, 200)
        self.assertContains(dialog_response, "Edit")
        self.assertContains(dialog_response, "Remove")
        self.assertContains(
            dialog_response,
            "This facility is unavailable for the full day.",
        )

    def test_all_facilities_day_is_disabled_when_each_is_blocked_all_day(self):
        other_facility = Facility.objects.create(
            branch=self.branch,
            name="Test Gym",
            slug="test-gym",
        )
        selected_day = timezone.localdate() + timedelta(days=1)
        for facility in (self.facility, other_facility):
            self.create_unavailable(
                facility,
                selected_day,
                timedelta(),
                timedelta(days=1),
            )

        response = self.client.get(
            reverse("reservations", kwargs={"branch": self.branch.slug}),
            {"month": selected_day.strftime("%Y-%m")},
        )

        self.assertTrue(
            self.get_calendar_day(response, selected_day)["is_unavailable"]
        )
        self.assertContains(response, "Not available")

    def test_adjacent_blocks_can_make_a_full_day_unavailable(self):
        selected_day = timezone.localdate() + timedelta(days=1)
        self.create_unavailable(
            self.facility,
            selected_day,
            timedelta(),
            timedelta(hours=12),
        )
        self.create_unavailable(
            self.facility,
            selected_day,
            timedelta(hours=12),
            timedelta(days=1),
        )

        response = self.client.get(
            reverse("reservations", kwargs={"branch": self.branch.slug}),
            {
                "month": selected_day.strftime("%Y-%m"),
                "facility": self.facility.pk,
            },
        )

        self.assertTrue(
            self.get_calendar_day(response, selected_day)["is_unavailable"]
        )


class InventoryViewTests(TestCase):
    def setUp(self):
        self.user = User.object.create(
            username="inventory_staff",
            role=User.Role.Employee,
            phone_number_code="+1",
            phone_number="5551234599",
            email="inventory_staff@example.com",
            first_name="Inventory",
            last_name="Staff",
            is_superuser=True,
            is_active=True,
        )
        self.client.force_login(self.user)
        self.branch = Branch.objects.create(
            name="Inventory Branch",
            slug="inventory-branch",
            city="Test City",
            address="1 Inventory Street",
        )
        self.inventory_item = Inventory.objects.create(
            branch=self.branch,
            name="Pool Towels",
            sku="POOL-TOWELS",
            unit=Inventory.Unit.PACK,
            quantity_on_hand=12,
            reorder_level=5,
            unit_cost=Decimal("6.50"),
            notes="Back-of-house linen stock.",
        )
        InventoryTransaction.objects.create(
            inventory=self.inventory_item,
            transaction_type=InventoryTransaction.Type.RECEIVED,
            quantity_change=12,
            balance_before=0,
            balance_after=12,
            unit_cost=Decimal("6.50"),
            performed_by=self.user,
            reference="Initial stock",
            notes="Opening inventory",
        )
        self.asset = InventoryAsset.objects.create(
            branch=self.branch,
            name="Pool Vacuum",
            asset_tag="ASSET-POOL-01",
            category="Pool equipment",
        )
        self.asset.record_event(
            event_type="borrowed",
            performed_by=self.user,
            borrower=self.user,
            notes="Assigned for scheduled cleaning.",
        )

    def test_dashboard_shows_red_overdue_assets_card_linking_to_asset_activity(self):
        self.asset.due_date = timezone.now() - timedelta(minutes=1)
        self.asset.save(update_fields=["due_date"])

        response = self.client.get(f"/dashboard/{self.branch.slug}/")

        activity_url = reverse(
            "inventory-asset-activity",
            kwargs={"branch": self.branch.slug},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overdue_assets_count"], 1)
        self.assertContains(response, "Borrowed assets past due")
        self.assertContains(response, 'class="card bg-error text-error-content')
        self.assertContains(response, f'href="{activity_url}"')
        self.assertContains(response, ">1</p>")

    def test_dashboard_hides_overdue_assets_card_when_none_are_past_due(self):
        response = self.client.get(f"/dashboard/{self.branch.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overdue_assets_count"], 0)
        self.assertNotContains(response, "Borrowed assets past due")

    def test_inventory_page_renders_summary_and_recent_activity(self):
        response = self.client.get(
            reverse("inventory", kwargs={"branch": self.branch.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory")
        self.assertContains(response, "Pool Towels")
        self.assertContains(response, "Initial stock")
        self.assertContains(response, "12")
        self.assertContains(response, "Low stock")

    def test_inventory_page_shows_overdue_assets_card_linking_to_asset_activity(self):
        self.asset.due_date = timezone.now() - timedelta(minutes=1)
        self.asset.save(update_fields=["due_date"])

        response = self.client.get(
            reverse("inventory", kwargs={"branch": self.branch.slug})
        )

        activity_url = reverse(
            "inventory-asset-activity",
            kwargs={"branch": self.branch.slug},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overdue_assets_count"], 1)
        self.assertContains(response, "Borrowed assets past due")
        self.assertContains(response, 'class="card mt-4 bg-error text-error-content')
        self.assertContains(response, f'href="{activity_url}"')
        self.assertContains(response, ">1</p>")
        self.assertContains(response, "Recent activity")
        self.assertContains(response, "Inventory assets")
        self.assertContains(response, "At/below reorder level:")
        self.assertNotContains(response, "Healthy:")
        self.assertContains(response, "Pool Vacuum")
        self.assertContains(response, "ASSET-POOL-01")
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'name="type"')
        self.assertContains(
            response,
            reverse("inventory-search", kwargs={"branch": self.branch.slug}),
        )
        self.assertContains(response, ">All</option>")
        self.assertContains(response, ">Inventory items</option>")
        self.assertContains(response, ">Assets</option>")
        self.assertContains(response, "Inventory asset activity")
        self.assertContains(response, "View all", count=2)
        self.assertContains(response, "Borrowed")
        self.assertContains(response, "Assigned for scheduled cleaning.")
        self.assertContains(response, "space-y-3 p-3 xl:hidden", count=2)
        self.assertContains(response, "hidden overflow-x-auto xl:block", count=2)
        self.assertContains(response, "min-w-[48rem]")
        self.assertContains(response, "min-w-[64rem]")

    def test_record_movement_page_renders_type_tabs_and_branch_items(self):
        response = self.client.get(
            reverse(
                "record-inventory-movement",
                kwargs={"branch": self.branch.slug},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Record movement")
        self.assertContains(response, "Inventory items")
        self.assertContains(response, "Assets")
        self.assertContains(response, self.inventory_item.name)
        self.assertContains(response, 'name="transaction_type"')
        self.assertContains(response, 'id="movement-current-stock"')
        self.assertNotContains(response, 'name="adjustment_direction"')
        self.assertContains(response, 'href="?type=asset"')
        self.assertContains(
            response,
            f'<option value="{self.inventory_item.pk}">{self.inventory_item.name}</option>',
            html=True,
        )
        self.assertNotContains(
            response,
            f'<option value="{self.inventory_item.pk}">{self.branch.name} - {self.inventory_item.name}</option>',
            html=True,
        )

    def test_record_inventory_movement_updates_stock_and_records_transaction(self):
        response = self.client.post(
            reverse(
                "record-inventory-movement",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "item_type": "inventory",
                "inventory": str(self.inventory_item.pk),
                "transaction_type": InventoryTransaction.Type.RECEIVED,
                "quantity": "4",
                "unit_cost": "7.25",
                "notes": "Four new packs.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "inventory-item-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "item_id": self.inventory_item.pk,
                },
            ),
        )
        self.inventory_item.refresh_from_db()
        transaction_record = self.inventory_item.transactions.first()
        self.assertEqual(self.inventory_item.quantity_on_hand, 16)
        self.assertEqual(transaction_record.quantity_change, 4)
        self.assertEqual(transaction_record.balance_before, 12)
        self.assertEqual(transaction_record.balance_after, 16)
        self.assertEqual(transaction_record.unit_cost, Decimal("7.25"))
        self.assertRegex(
            transaction_record.reference,
            r"^INV-\d{8}-[A-F0-9]{8}$",
        )
        self.assertEqual(transaction_record.performed_by, self.user)

    def test_record_inventory_movement_rejects_consumption_below_zero(self):
        response = self.client.post(
            reverse(
                "record-inventory-movement",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "item_type": "inventory",
                "inventory": str(self.inventory_item.pk),
                "transaction_type": InventoryTransaction.Type.CONSUMED,
                "quantity": "13",
                "notes": "Invalid over-consumption.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.quantity_on_hand, 12)
        self.assertEqual(self.inventory_item.transactions.count(), 1)
        self.assertContains(response, "would make stock negative")

    def test_adjustments_and_returns_require_notes(self):
        url = reverse(
            "record-inventory-movement",
            kwargs={"branch": self.branch.slug},
        )
        for transaction_type in (
            InventoryTransaction.Type.ADJUSTMENT,
            InventoryTransaction.Type.RETURNED,
        ):
            with self.subTest(transaction_type=transaction_type):
                response = self.client.post(
                    url,
                    {
                        "item_type": "inventory",
                        "inventory": str(self.inventory_item.pk),
                        "transaction_type": transaction_type,
                        "quantity": "2",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    "A note is required for adjustments and returns.",
                )
                self.assertEqual(self.inventory_item.transactions.count(), 1)

    def test_adjustment_sets_target_stock_and_prepends_server_generated_note(self):
        url = reverse(
            "record-inventory-movement",
            kwargs={"branch": self.branch.slug},
        )

        increase_response = self.client.post(
            url,
            {
                "item_type": "inventory",
                "inventory": str(self.inventory_item.pk),
                "transaction_type": InventoryTransaction.Type.ADJUSTMENT,
                "quantity": "15",
                "notes": "Cycle count found extra stock.",
            },
        )

        self.assertRedirects(
            increase_response,
            reverse(
                "inventory-item-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "item_id": self.inventory_item.pk,
                },
            ),
        )
        increase = self.inventory_item.transactions.first()
        self.assertEqual(increase.quantity_change, 3)
        self.assertEqual(increase.balance_before, 12)
        self.assertEqual(increase.balance_after, 15)
        self.assertEqual(
            increase.notes,
            "Increase stock to 15: Cycle count found extra stock.",
        )

        decrease_response = self.client.post(
            url,
            {
                "item_type": "inventory",
                "inventory": str(self.inventory_item.pk),
                "transaction_type": InventoryTransaction.Type.ADJUSTMENT,
                "quantity": "4",
                "notes": "Damaged stock removed.",
            },
        )

        self.assertRedirects(
            decrease_response,
            reverse(
                "inventory-item-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "item_id": self.inventory_item.pk,
                },
            ),
        )
        decrease = self.inventory_item.transactions.first()
        self.assertEqual(decrease.quantity_change, -11)
        self.assertEqual(decrease.balance_before, 15)
        self.assertEqual(decrease.balance_after, 4)
        self.assertEqual(decrease.notes, "Decrease stock to 4: Damaged stock removed.")

    def test_adjustment_rejects_target_matching_current_stock(self):
        response = self.client.post(
            reverse(
                "record-inventory-movement",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "item_type": "inventory",
                "inventory": str(self.inventory_item.pk),
                "transaction_type": InventoryTransaction.Type.ADJUSTMENT,
                "quantity": "12",
                "notes": "No actual adjustment.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.quantity_on_hand, 12)
        self.assertEqual(self.inventory_item.transactions.count(), 1)
        self.assertContains(response, "already matches the current stock")

    def test_record_asset_return_updates_status_and_history(self):
        response = self.client.post(
            reverse(
                "record-inventory-movement",
                kwargs={"branch": self.branch.slug},
            ),
            {
                "item_type": "asset",
                "asset": str(self.asset.pk),
                "event_type": InventoryAssetHistory.Event.RETURNED,
                "notes": "Returned to the equipment room.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": self.asset.pk},
            ),
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, InventoryAsset.Status.ACTIVE)
        self.assertIsNone(self.asset.borrowed_by)
        self.assertEqual(self.asset.history.count(), 2)
        self.assertEqual(
            self.asset.history.first().event_type,
            InventoryAssetHistory.Event.RETURNED,
        )

    def test_asset_borrower_uses_search_picker_modal(self):
        response = self.client.get(
            reverse(
                "record-inventory-movement",
                kwargs={"branch": self.branch.slug},
            ),
            {"type": "asset"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find a borrower")
        self.assertContains(response, 'data-user-picker')
        self.assertContains(response, 'data-user-picker-id')
        self.assertContains(
            response,
            reverse(
                "search-reservation-guests",
                kwargs={"branch": self.branch.slug},
            ),
        )
        self.assertContains(response, "reservation-user-picker.js")
        self.assertContains(response, 'name="borrower"')
        self.assertContains(response, 'type="hidden"')
        self.assertContains(response, 'name="due_date"')
        self.assertContains(response, 'type="datetime-local"')

    def test_record_asset_borrow_requires_borrower_and_updates_asset(self):
        asset = InventoryAsset.objects.create(
            branch=self.branch,
            name="Available Pool Equipment",
            asset_tag="ASSET-POOL-AVAILABLE",
            category="Equipment",
        )
        url = reverse(
            "record-inventory-movement",
            kwargs={"branch": self.branch.slug},
        )
        response = self.client.post(
            url,
            {
                "item_type": "asset",
                "asset": str(asset.pk),
                "event_type": InventoryAssetHistory.Event.BORROWED,
                "notes": "Assigned for a shift.",
            },
        )

        self.assertEqual(response.status_code, 200)
        asset.refresh_from_db()
        self.assertEqual(asset.status, InventoryAsset.Status.ACTIVE)
        self.assertEqual(asset.history.count(), 0)
        self.assertContains(response, "Choose a borrower for this event.")

        response = self.client.post(
            url,
            {
                "item_type": "asset",
                "asset": str(asset.pk),
                "event_type": InventoryAssetHistory.Event.BORROWED,
                "borrower": str(self.user.pk),
                "due_date": "2026-10-20T14:30",
                "notes": "Assigned for a shift.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": asset.pk},
            ),
        )
        asset.refresh_from_db()
        self.assertEqual(asset.status, InventoryAsset.Status.BORROWED)
        self.assertEqual(asset.borrowed_by, self.user)
        self.assertEqual(
            timezone.localtime(asset.due_date).strftime("%Y-%m-%dT%H:%M"),
            "2026-10-20T14:30",
        )
        event = asset.history.first()
        self.assertEqual(event.event_type, InventoryAssetHistory.Event.BORROWED)
        self.assertEqual(event.borrower, self.user)
        self.assertEqual(
            timezone.localtime(event.due_date).strftime("%Y-%m-%dT%H:%M"),
            "2026-10-20T14:30",
        )

        response = self.client.post(
            url,
            {
                "item_type": "asset",
                "asset": str(asset.pk),
                "event_type": InventoryAssetHistory.Event.MAINTENANCE_STARTED,
                "notes": "This is not allowed while borrowed.",
            },
        )

        self.assertEqual(response.status_code, 200)
        asset.refresh_from_db()
        self.assertEqual(asset.status, InventoryAsset.Status.BORROWED)
        self.assertEqual(asset.history.count(), 1)
        self.assertContains(
            response,
            "This event is not available for the asset's current status.",
        )

    def test_inventory_search_shows_matching_items_and_assets_as_cards(self):
        response = self.client.get(
            reverse("inventory-search", kwargs={"branch": self.branch.slug}),
            {"q": "pool", "type": "all"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pool Towels")
        self.assertContains(response, "Inventory item")
        self.assertContains(response, "Pool Vacuum")
        self.assertContains(response, "Asset")
        self.assertContains(response, "ASSET-POOL-01")

    def test_inventory_search_filters_by_type_and_branch(self):
        other_branch = Branch.objects.create(
            name="Other Search Branch",
            slug="other-search-branch",
            city="Other City",
            address="3 Inventory Street",
        )
        Inventory.objects.create(
            branch=other_branch,
            name="Other Branch Pool Towels",
            sku="OTHER-POOL-TOWELS",
            unit=Inventory.Unit.PACK,
        )

        response = self.client.get(
            reverse("inventory-search", kwargs={"branch": self.branch.slug}),
            {"q": "pool", "type": "items"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["results"]), 1)
        self.assertContains(response, "Pool Towels")
        self.assertNotContains(response, "Pool Vacuum")
        self.assertNotContains(response, "Other Branch Pool Towels")

    def test_inventory_activity_limits_recent_items_and_shows_full_lists(self):
        for index in range(2):
            InventoryTransaction.objects.create(
                inventory=self.inventory_item,
                transaction_type=InventoryTransaction.Type.RECEIVED,
                quantity_change=1,
                balance_before=12 + index,
                balance_after=13 + index,
                performed_by=self.user,
                reference=f"Extra stock {index}",
            )
            InventoryAsset.objects.create(
                branch=self.branch,
                name=f"Extra asset {index}",
                asset_tag=f"ASSET-EXTRA-{index}",
                category="Equipment",
            ).record_event(
                event_type="acquired",
                performed_by=self.user,
                notes=f"Added asset {index}.",
            )

        response = self.client.get(
            reverse("inventory", kwargs={"branch": self.branch.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["recent_transactions"]), 2)
        self.assertEqual(len(response.context["recent_asset_events"]), 2)

        transactions_response = self.client.get(
            reverse("inventory-transactions", kwargs={"branch": self.branch.slug})
        )
        asset_activity_response = self.client.get(
            reverse("inventory-asset-activity", kwargs={"branch": self.branch.slug})
        )
        self.assertEqual(transactions_response.status_code, 200)
        self.assertEqual(len(transactions_response.context["transactions"]), 3)
        self.assertContains(transactions_response, "Extra stock 0")
        self.assertEqual(asset_activity_response.status_code, 200)
        self.assertEqual(len(asset_activity_response.context["asset_events"]), 3)
        self.assertContains(asset_activity_response, "Extra asset 0")

    def test_asset_activity_lists_only_past_due_borrowed_assets(self):
        self.asset.due_date = timezone.now() - timedelta(minutes=1)
        self.asset.save(update_fields=["due_date"])
        due_soon_asset = InventoryAsset.objects.create(
            branch=self.branch,
            name="Due Soon Asset",
            asset_tag="ASSET-DUE-SOON",
            category="Equipment",
            status=InventoryAsset.Status.BORROWED,
            borrowed_by=self.user,
            due_date=timezone.now() + timedelta(minutes=1),
        )
        other_branch = Branch.objects.create(
            name="Other Overdue Branch",
            slug="other-overdue-branch",
            city="Other City",
            address="4 Inventory Street",
        )
        InventoryAsset.objects.create(
            branch=other_branch,
            name="Other Branch Overdue Asset",
            asset_tag="ASSET-OTHER-OVERDUE",
            category="Equipment",
            status=InventoryAsset.Status.BORROWED,
            borrowed_by=self.user,
            due_date=timezone.now() - timedelta(minutes=2),
        )

        response = self.client.get(
            reverse(
                "inventory-asset-activity",
                kwargs={"branch": self.branch.slug},
            )
        )

        self.assertEqual(response.status_code, 200)
        overdue_assets = list(response.context["overdue_assets"])
        self.assertEqual([asset.pk for asset in overdue_assets], [self.asset.pk])
        self.assertContains(response, "Borrowed assets past due")
        self.assertContains(response, self.asset.asset_tag)
        self.assertContains(response, str(self.user))
        self.assertNotContains(response, due_soon_asset.asset_tag)
        self.assertNotContains(response, "Other Branch Overdue Asset")

    def test_asset_activity_hides_past_due_table_when_no_assets_are_overdue(self):
        response = self.client.get(
            reverse(
                "inventory-asset-activity",
                kwargs={"branch": self.branch.slug},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Borrowed assets past due")

    def test_inventory_item_detail_shows_details_and_history(self):
        response = self.client.get(
            reverse(
                "inventory-item-detail",
                kwargs={"branch": self.branch.slug, "item_id": self.inventory_item.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["hide_aside"])
        self.assertNotContains(response, "<aside")
        self.assertContains(response, "Pool Towels")
        self.assertContains(response, "POOL-TOWELS")
        self.assertContains(response, "Item details")
        self.assertContains(response, "Inventory history")
        self.assertContains(response, "Initial stock")
        self.assertContains(response, "12")

    def test_inventory_transaction_detail_shows_transaction_details(self):
        response = self.client.get(
            reverse(
                "inventory-transaction-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "transaction_id": self.inventory_item.transactions.first().pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["hide_aside"])
        self.assertContains(response, "Pool Towels")
        self.assertContains(response, "Transaction details")
        self.assertContains(response, "Balance after")
        self.assertContains(response, "Initial stock")

    def test_inventory_asset_detail_shows_details_and_history(self):
        response = self.client.get(
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": self.asset.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["hide_aside"])
        self.assertNotContains(response, "<aside")
        self.assertContains(response, "Pool Vacuum")
        self.assertContains(response, "ASSET-POOL-01")
        self.assertContains(response, "Pool equipment")
        self.assertContains(response, "Asset history")
        self.assertContains(response, "Borrowed")
        self.assertContains(response, 'name="status"')
        self.assertContains(response, 'name="notes"')
        self.assertContains(response, "Add an asset history note")
        self.assertContains(response, 'option value="active"')
        self.assertNotContains(response, 'option value="borrowed"')
        self.assertNotContains(response, "Edit asset")

    def test_inventory_asset_detail_is_limited_to_the_requested_branch(self):
        other_branch = Branch.objects.create(
            name="Other Inventory Branch",
            slug="other-inventory-branch",
            city="Other City",
            address="2 Inventory Street",
        )
        other_asset = InventoryAsset.objects.create(
            branch=other_branch,
            name="Other Branch Asset",
            asset_tag="ASSET-OTHER-01",
            category="Equipment",
        )

        response = self.client.get(
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": other_asset.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_inventory_asset_status_can_be_changed_and_recorded(self):
        response = self.client.post(
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": self.asset.pk},
            ),
            {
                "status": InventoryAsset.Status.ACTIVE,
                "notes": "Returned after scheduled cleaning.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": self.asset.pk},
            ),
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, InventoryAsset.Status.ACTIVE)
        self.assertIsNone(self.asset.borrowed_by)
        self.assertIsNone(self.asset.due_date)
        event = self.asset.history.first()
        self.assertEqual(event.event_type, InventoryAssetHistory.Event.RETURNED)
        self.assertEqual(event.borrower, self.user)
        self.assertEqual(event.notes, "Returned after scheduled cleaning.")

    def test_inventory_asset_rejects_invalid_status_transition(self):
        response = self.client.post(
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": self.asset.pk},
            ),
            {
                "status": InventoryAsset.Status.DISPOSED,
                "notes": "Attempted an invalid transition.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, InventoryAsset.Status.BORROWED)
        self.assertEqual(self.asset.history.count(), 1)

    def test_inventory_asset_status_change_requires_history_notes(self):
        response = self.client.post(
            reverse(
                "inventory-asset-detail",
                kwargs={"branch": self.branch.slug, "asset_id": self.asset.pk},
            ),
            {"status": InventoryAsset.Status.ACTIVE, "notes": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, InventoryAsset.Status.BORROWED)
        self.assertEqual(self.asset.history.count(), 1)
        self.assertContains(response, "This field is required.")

    def test_creating_inventory_and_asset_records_transaction_and_history(self):
        item = Inventory.objects.create(
            branch=self.branch,
            name="Model Test Cleaning Supplies",
            sku="MODEL-CLEANING-01",
            unit=Inventory.Unit.BOTTLE,
            reorder_level=3,
            unit_cost=Decimal("12.50"),
        )

        transaction_record = item.record_transaction(
            transaction_type=InventoryTransaction.Type.RECEIVED,
            quantity_change=6,
            performed_by=self.user,
            reference="Model test receipt",
        )

        self.assertEqual(item.quantity_on_hand, 6)
        self.assertEqual(transaction_record.inventory, item)
        self.assertEqual(transaction_record.balance_before, 0)
        self.assertEqual(transaction_record.balance_after, 6)
        self.assertEqual(transaction_record.quantity_change, 6)
        self.assertEqual(transaction_record.performed_by, self.user)
        self.assertTrue(
            InventoryTransaction.objects.filter(pk=transaction_record.pk).exists()
        )

        asset = InventoryAsset.objects.create(
            branch=self.branch,
            name="Model Test Vacuum",
            asset_tag="ASSET-MODEL-TEST-01",
            category="Cleaning equipment",
        )
        acquired_event = asset.record_event(
            event_type=InventoryAssetHistory.Event.ACQUIRED,
            performed_by=self.user,
            notes="Asset added in model test.",
        )
        borrowed_event = asset.record_event(
            event_type=InventoryAssetHistory.Event.BORROWED,
            performed_by=self.user,
            borrower=self.user,
            notes="Asset borrowed in model test.",
        )

        asset.refresh_from_db()
        self.assertEqual(asset.status, InventoryAsset.Status.BORROWED)
        self.assertEqual(asset.borrowed_by, self.user)
        self.assertEqual(acquired_event.status_before, InventoryAsset.Status.ACTIVE)
        self.assertEqual(acquired_event.status_after, InventoryAsset.Status.ACTIVE)
        self.assertEqual(borrowed_event.status_before, InventoryAsset.Status.ACTIVE)
        self.assertEqual(borrowed_event.status_after, InventoryAsset.Status.BORROWED)
        self.assertEqual(borrowed_event.borrower, self.user)
        self.assertEqual(asset.history.count(), 2)
        self.assertTrue(
            InventoryAssetHistory.objects.filter(pk=borrowed_event.pk).exists()
        )

    def test_seed_inventory_demo_command_is_idempotent(self):
        call_command("seed_inventory_demo", self.branch.slug)
        call_command("seed_inventory_demo", self.branch.slug)

        item = Inventory.objects.get(sku="DEMO-POOL-TOWELS")
        self.assertEqual(item.branch, self.branch)
        self.assertEqual(item.quantity_on_hand, 12)
        self.assertEqual(item.transactions.count(), 1)
        self.assertEqual(
            item.transactions.get().reference,
            "Demo seed opening stock",
        )

        asset = InventoryAsset.objects.get(asset_tag="DEMO-ASSET-POOL-01")
        self.assertEqual(asset.branch, self.branch)
        self.assertEqual(asset.history.count(), 1)
        self.assertEqual(
            asset.history.get().event_type,
            InventoryAssetHistory.Event.ACQUIRED,
        )

    def test_add_inventory_page_renders_both_item_type_tabs(self):
        stock_response = self.client.get(
            reverse(
                "add-inventory-item",
                kwargs={"branch": self.branch.slug},
            )
        )
        asset_response = self.client.get(
            reverse(
                "add-inventory-item",
                kwargs={"branch": self.branch.slug},
            ),
            {"type": "asset"},
        )

        self.assertEqual(stock_response.status_code, 200)
        self.assertTrue(stock_response.context["hide_aside"])
        self.assertNotContains(stock_response, "<aside")
        self.assertContains(stock_response, "Add stock item")
        self.assertContains(stock_response, "Opening quantity")
        self.assertEqual(asset_response.status_code, 200)
        self.assertTrue(asset_response.context["hide_aside"])
        self.assertNotContains(asset_response, "<aside")
        self.assertContains(asset_response, "Add tracked asset")
        self.assertContains(asset_response, "Asset tag")
        self.assertContains(asset_response, 'list="resort-asset-categories"')
        self.assertContains(asset_response, "Kitchen equipment")
        self.assertContains(asset_response, "Brand")
        self.assertNotContains(asset_response, "Facility")

    def test_add_inventory_page_can_create_stock_with_opening_transaction(self):
        response = self.client.post(
            reverse(
                "add-inventory-item",
                kwargs={"branch": self.branch.slug},
            )
            + "?type=stock",
            {
                "item_type": "stock",
                "name": "Pool Sanitizer",
                "sku": "SANITIZER-01",
                "unit": Inventory.Unit.LITER,
                "opening_quantity": "8",
                "reorder_level": "2",
                "unit_cost": "24.50",
                "notes": "Liquid treatment.",
            },
        )

        self.assertRedirects(
            response,
            reverse("inventory", kwargs={"branch": self.branch.slug}),
        )
        item = Inventory.objects.get(sku="SANITIZER-01")
        self.assertEqual(item.branch, self.branch)
        self.assertEqual(item.quantity_on_hand, 8)
        transaction_record = InventoryTransaction.objects.get(inventory=item)
        self.assertEqual(transaction_record.quantity_change, 8)
        self.assertEqual(
            transaction_record.transaction_type,
            InventoryTransaction.Type.RECEIVED,
        )
        self.assertEqual(transaction_record.performed_by, self.user)

    def test_add_inventory_page_can_create_asset_with_acquired_history(self):
        response = self.client.post(
            reverse(
                "add-inventory-item",
                kwargs={"branch": self.branch.slug},
            )
            + "?type=asset",
            {
                "item_type": "asset",
                "name": "Poolside Umbrella",
                "asset_tag": "ASSET-UMBRELLA-02",
                "category": "Outdoor furniture",
                "brand": "Resort Living",
                "serial_number": "",
                "purchase_date": "2026-10-01",
                "purchase_cost": "4500.00",
                "notes": "",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "inventory-asset-detail",
                kwargs={
                    "branch": self.branch.slug,
                    "asset_id": InventoryAsset.objects.get(
                        asset_tag="ASSET-UMBRELLA-02"
                    ).pk,
                },
            ),
        )
        asset = InventoryAsset.objects.get(asset_tag="ASSET-UMBRELLA-02")
        self.assertEqual(asset.branch, self.branch)
        self.assertEqual(asset.brand, "Resort Living")
        self.assertEqual(asset.category, "Outdoor furniture")
        self.assertEqual(asset.status, InventoryAsset.Status.ACTIVE)
        inventory_response = self.client.get(
            reverse("inventory", kwargs={"branch": self.branch.slug})
        )
        self.assertContains(inventory_response, "Resort Living")
        event = asset.history.get()
        self.assertEqual(event.event_type, "acquired")
        self.assertEqual(event.performed_by, self.user)
