from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import User
from dashboard.models import Branch, Calendar, Facility, Payment, Reservation


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
        self.assertNotContains(response, 'name="party_size"')
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
        self.assertNotContains(response, 'name="party_size"')
        self.assertNotContains(response, "special_requests")
        self.assertNotContains(response, "name=\"status\"")

    def test_calendar_booking_is_confirmed_and_added_to_calendar(self):
        self.facility.rate_morning = 90
        self.facility.save()
        guest = User.object.create(
            username="direct_booking_guest",
            role=User.Role.User,
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
        reservation, entry = self.create_calendar_reservation(
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
            calendar_entry=entry,
            amount=Decimal("50.00"),
            currency="PHP",
            method=Payment.Method.CASH,
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
        self.assertContains(response, "receipt-123")
        self.assertContains(response, "Edit booking")

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
                Reservation.Status.CONFIRMED,
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
                if reservation_status is not None:
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
                calendar_entry = Calendar.objects.get(
                    reservation=reservation
                )
                self.assertEqual(
                    reservation.raw_amount,
                    expected_amount,
                )
                self.assertEqual(reservation.party_size, 1)
                self.assertEqual(reservation.discount, Decimal("12.50"))
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
                "guest": str(reservation.guest_id),
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
