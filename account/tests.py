from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.forms import PasswordInput
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import OTP_EXPIRY_DURATION, User
from .views.security import mask_email
from dashboard.models import Branch, Calendar, Facility, Reservation


class EmailVerificationLoginTests(TestCase):
    def create_unverified_user(self, username):
        return User.object.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            first_name="Test",
            last_name="User",
            phone_number_code="+1",
            phone_number="5555550300",
            email_confirmation_token="old-token",
        )

    def log_in(self, user):
        return self.client.post(
            reverse("login"),
            {"username": user.username, "password": "TestPassword123!"},
        )

    @patch("account.views.login.send_mail")
    def test_unverified_login_generates_and_emails_token_with_24_hour_expiry(self, send_mail):
        user = self.create_unverified_user("verify_login")
        generated_at = timezone.now()
        user.email_confirmation_expiresat = None
        user.save(update_fields=["email_confirmation_expiresat"])

        with patch("account.views.login.timezone.now", return_value=generated_at):
            response = self.log_in(user)

        user.refresh_from_db()
        self.assertTemplateUsed(response, "verify_email.html")
        self.assertEqual(user.email_confirmation_expiresat, generated_at + timedelta(hours=24))
        self.assertNotEqual(user.email_confirmation_token, "old-token")
        send_mail.assert_called_once()
        self.assertIn(user.email_confirmation_token, send_mail.call_args.kwargs["message"])

    @patch("account.views.login.send_mail")
    def test_unverified_login_renews_at_80_percent_elapsed_boundary(self, send_mail):
        user = self.create_unverified_user("verify_boundary")
        now = timezone.now()
        user.email_confirmation_expiresat = now + timedelta(hours=4, minutes=48)
        user.save(update_fields=["email_confirmation_expiresat"])

        with patch("account.views.login.timezone.now", return_value=now):
            self.log_in(user)

        send_mail.assert_called_once()
        user.refresh_from_db()
        self.assertEqual(user.email_confirmation_expiresat, now + timedelta(hours=24))

    @patch("account.views.login.send_mail")
    def test_unverified_login_does_not_renew_before_80_percent_elapsed(self, send_mail):
        user = self.create_unverified_user("verify_not_due")
        now = timezone.now()
        expires_at = now + timedelta(hours=4, minutes=49)
        user.email_confirmation_expiresat = expires_at
        user.save(update_fields=["email_confirmation_expiresat"])

        response = self.log_in(user)

        self.assertTemplateUsed(response, "verify_email.html")
        send_mail.assert_not_called()
        user.refresh_from_db()
        self.assertEqual(user.email_confirmation_expiresat, expires_at)

    def test_verification_link_confirms_email_and_clears_token(self):
        user = self.create_unverified_user("verify_link")
        user.email_confirmation_expiresat = timezone.now() + timedelta(hours=24)
        user.save(update_fields=["email_confirmation_expiresat"])

        response = self.client.get(
            reverse("verify-email", kwargs={"token": user.email_confirmation_token})
        )

        user.refresh_from_db()
        self.assertTemplateUsed(response, "email_verified.html")
        self.assertContains(response, "Email verified successfully")
        self.assertIsNotNone(user.email_confirmed_at)
        self.assertIsNone(user.email_confirmation_token)
        self.assertIsNone(user.email_confirmation_expiresat)


class AdminUserPasswordFormTests(TestCase):
    def test_admin_creation_masks_confirms_and_hashes_password(self):
        password = "mV3!qL8#zP0$rT9"
        form_data = {
            "username": "admin_password_test",
            "email": "admin_password_test@example.com",
            "first_name": "Admin",
            "middle_name": "Middle",
            "last_name": "Test",
            "phone_number_code": "+1",
            "phone_number": "5555550142",
            "role": User.Role.Employee,
            "is_active": "on",
            "password1": password,
            "password2": password,
        }
        form = AdminUserCreationForm(data=form_data)

        self.assertIsInstance(form.fields["password1"].widget, PasswordInput)
        self.assertIsInstance(form.fields["password2"].widget, PasswordInput)
        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))

    def test_admin_creation_rejects_mismatched_passwords(self):
        form_data = {
            "username": "admin_password_mismatch",
            "email": "admin_password_mismatch@example.com",
            "first_name": "Admin",
            "middle_name": "Middle",
            "last_name": "Test",
            "phone_number_code": "+1",
            "phone_number": "5555550143",
            "role": User.Role.Employee,
            "password1": "AdminSetupPassword_42!",
            "password2": "DifferentSetupPassword_43!",
        }
        form = AdminUserCreationForm(data=form_data)

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_admin_change_form_does_not_expose_password_as_editable_text(self):
        form = AdminUserChangeForm()

        self.assertIsInstance(form.fields["password"].widget, ReadOnlyPasswordHashWidget)


class UserRoleCreationTests(TestCase):
    def test_creates_one_account_for_each_role(self):
        for index, (role, _label) in enumerate(User.Role.choices):
            User.object.create_user(
                email=f"user{index}@example.com",
                first_name="test",
                last_name="user",
                password="test-password",
                username=f"user{index}",
                role=role,
                phone_number_code="+1",
                phone_number=f"555000{index:04d}",
            )

        self.assertEqual(User.object.count(), len(User.Role.choices))
        for role, _label in User.Role.choices:
            with self.subTest(role=role):
                self.assertEqual(User.object.filter(role=role).count(), 1)


class UserProfileTests(TestCase):
    def setUp(self):
        self.owner = User.object.create_user(
            username="profile_owner",
            email="owner@example.com",
            password="TestPassword123!",
            first_name="Profile",
            middle_name="Middle",
            last_name="Owner",
            phone_number_code="+1",
            phone_number="5555550301",
            avatar_url=None,
        )
        self.other_user = User.object.create_user(
            username="profile_other",
            email="other@example.com",
            password="TestPassword123!",
            first_name="Other",
            last_name="Person",
            phone_number_code="+1",
            phone_number="5555550302",
        )

    def test_owner_can_view_profile_with_contact_info_and_no_security_fields(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("user-profile", kwargs={"username": self.owner.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile Middle Owner")
        self.assertContains(response, "owner@example.com")
        self.assertContains(response, "5555550301")
        self.assertContains(response, "Settings")
        self.assertNotContains(response, "totp_secret")
        self.assertNotContains(response, "otp_code")

    def test_profile_shows_reservation_and_booking_history(self):
        branch = Branch.objects.create(
            name="Profile Resort",
            slug="profile-resort",
            city="Test City",
            address="1 Test Street",
        )
        facility = Facility.objects.create(
            branch=branch,
            name="Ocean Pool",
            slug="profile-ocean-pool",
        )
        starts_at = timezone.now() + timedelta(days=2)
        ends_at = starts_at + timedelta(hours=3)
        reservation = Reservation.objects.create(
            guest=self.owner,
            facility=facility,
            starts_at=starts_at,
            ends_at=ends_at,
            status=Reservation.Status.CONFIRMED,
        )
        Calendar.objects.create(
            reservation=reservation,
            facility=facility,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        Reservation.objects.create(
            guest=self.owner,
            facility=facility,
            starts_at=starts_at + timedelta(days=1),
            ends_at=ends_at + timedelta(days=1),
            status=Reservation.Status.PENDING,
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("user-profile", kwargs={"username": self.owner.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reservation &amp; booking history")
        self.assertContains(response, "Ocean Pool")
        self.assertContains(response, "Booking")
        self.assertContains(response, "Reservation")
        self.assertContains(response, "Confirmed")
        self.assertContains(response, "Pending")
        self.assertContains(response, "2 total")
        for reservation in self.owner.reservations.all():
            self.assertContains(
                response,
                reverse(
                    "public-reservation-detail",
                    kwargs={"reservation_id": reservation.pk},
                ),
            )

    def test_superuser_profile_has_badge_after_username(self):
        self.owner.is_superuser = True
        self.owner.save(update_fields=["is_superuser"])
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("user-profile", kwargs={"username": self.owner.username})
        )

        self.assertContains(response, "@profile_owner")
        self.assertContains(response, "profile-superuser-badge")
        self.assertContains(response, ">Superuser</span>")

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(
            reverse("user-profile", kwargs={"username": self.owner.username})
        )

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('user-profile', kwargs={'username': self.owner.username})}",
        )

    def test_regular_user_cannot_view_another_users_profile(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("user-profile", kwargs={"username": self.other_user.username})
        )

        self.assertEqual(response.status_code, 403)

    def test_non_user_role_can_view_another_users_profile(self):
        employee = User.object.create_user(
            username="profile_employee",
            email="employee@example.com",
            password="TestPassword123!",
            first_name="Staff",
            last_name="Member",
            phone_number_code="+1",
            phone_number="5555550303",
            role=User.Role.Employee,
        )
        self.client.force_login(employee)

        response = self.client.get(
            reverse("user-profile", kwargs={"username": self.other_user.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Other Person")
        self.assertNotContains(
            response,
            reverse("user-settings", kwargs={"username": self.other_user.username}),
        )

    def test_owner_can_manage_settings_without_exposing_avatar_url(self):
        self.owner.avatar_url = "https://example.com/avatar.jpg"
        self.owner.save(update_fields=["avatar_url"])
        self.client.force_login(self.owner)

        edit_url = reverse(
            "user-settings", kwargs={"username": self.owner.username}
        )
        get_response = self.client.get(edit_url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Settings")
        self.assertNotContains(get_response, "Edit profile")
        self.assertContains(get_response, "Delete account")
        self.assertContains(get_response, "This action cannot be undone.")
        self.assertContains(
            get_response,
            '<button type="button" class="btn btn-error btn-outline shrink-0">Delete account</button>',
        )
        self.assertNotContains(get_response, 'name="avatar_url"')

        response = self.client.post(
            edit_url,
            {
                "first_name": "Updated",
                "middle_name": "",
                "last_name": "Name",
                "phone_number_code": "+1",
                "phone_number": "5555550301",
                "avatar_url": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("user-profile", kwargs={"username": self.owner.username}),
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.first_name, "Updated")
        self.assertEqual(self.owner.avatar_url, "https://example.com/avatar.jpg")

    def test_user_cannot_edit_another_users_profile(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("user-settings", kwargs={"username": self.other_user.username}),
            {"first_name": "Changed"},
        )

        self.assertEqual(response.status_code, 403)
        self.other_user.refresh_from_db()
        self.assertEqual(self.other_user.first_name, "Other")

    def test_totp_settings_show_enable_button_when_totp_is_off(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("user-settings", kwargs={"username": self.owner.username})
        )

        self.assertContains(response, "Two-factor authentication")
        self.assertContains(response, "Turn on TOTP")
        self.assertNotContains(response, "Turn off TOTP")

    def test_totp_settings_show_change_and_disable_forms_when_enabled(self):
        self.owner.generate_totp_secret()
        self.owner.totp_enabled = True
        self.owner.save(update_fields=["totp_secret", "totp_enabled"])
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("user-settings", kwargs={"username": self.owner.username})
        )

        self.assertContains(response, "Change authenticator")
        self.assertContains(
            response,
            reverse(
                "change-totp-authenticator",
                kwargs={"username": self.owner.username},
            ),
        )
        self.assertNotContains(response, 'id="change-totp-code"')
        self.assertContains(response, "Turn off TOTP")
        self.assertContains(response, 'name="action" value="disable"')

    def test_totp_can_be_disabled_after_current_code_is_verified(self):
        self.owner.generate_totp_secret()
        self.owner.totp_enabled = True
        self.owner.save(update_fields=["totp_secret", "totp_enabled"])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("update-totp-settings", kwargs={"username": self.owner.username}),
            {
                "action": "disable",
                "totp_code": pyotp.TOTP(self.owner.totp_secret).now(),
            },
        )

        self.assertRedirects(
            response,
            reverse("user-settings", kwargs={"username": self.owner.username}),
        )
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.totp_enabled)
        self.assertEqual(self.owner.totp_secret, "")

    def test_totp_cannot_be_disabled_with_invalid_code(self):
        self.owner.generate_totp_secret()
        self.owner.totp_enabled = True
        self.owner.save(update_fields=["totp_secret", "totp_enabled"])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("update-totp-settings", kwargs={"username": self.owner.username}),
            {"action": "disable", "totp_code": "000000"},
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse("user-settings", kwargs={"username": self.owner.username}),
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.totp_enabled)
        self.assertContains(
            response,
            "The authenticator code was invalid or has expired.",
        )

    @patch.object(User, "send_otp_email")
    def test_totp_authenticator_change_uses_email_otp_before_new_setup(
        self, send_otp_email
    ):
        self.owner.generate_totp_secret()
        old_secret = self.owner.totp_secret
        self.owner.totp_enabled = True
        self.owner.save(update_fields=["totp_secret", "totp_enabled"])
        self.client.force_login(self.owner)

        def send_test_email(request, purpose):
            user = request.user
            user.otp_code = "123456"
            user.otp_expires_at = timezone.now() + OTP_EXPIRY_DURATION
            user.save(update_fields=["otp_code", "otp_expires_at", "updated_at"])
            return user.otp_code

        send_otp_email.side_effect = send_test_email
        change_url = reverse(
            "change-totp-authenticator",
            kwargs={"username": self.owner.username},
        )
        response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        send_otp_email.assert_called_once()
        self.assertEqual(
            send_otp_email.call_args.args[1],
            "authenticator change confirmation",
        )
        self.assertContains(response, "Email confirmation code")
        self.assertContains(response, "Resend code in")
        self.assertContains(response, "o******@example.com")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.totp_secret, old_secret)
        self.assertTrue(self.owner.totp_enabled)

        response = self.client.post(
            change_url,
            {"action": "confirm_email", "email_code": "000000"},
        )
        self.assertRedirects(
            response,
            change_url,
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.totp_secret, old_secret)
        self.assertTrue(self.owner.totp_enabled)

        self.owner.refresh_from_db()
        response = self.client.post(
            change_url,
            {"action": "confirm_email", "email_code": "123456"},
        )
        self.assertRedirects(response, change_url)
        self.assertNotIn("totp_change_email_user_id", self.client.session)
        new_secret = self.client.session["totp_change_setup_secret"]
        self.assertNotEqual(new_secret, old_secret)

        response = self.client.get(change_url)
        self.assertContains(response, "new-totp-code")
        response = self.client.post(
            change_url,
            {
                "action": "verify_totp",
                "totp_code": pyotp.TOTP(new_secret).now(),
            },
        )

        self.assertRedirects(
            response,
            reverse("user-settings", kwargs={"username": self.owner.username}),
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.totp_secret, new_secret)
        self.assertTrue(self.owner.totp_enabled)

    @patch.object(User, "send_otp_email")
    def test_authenticator_change_resend_obeys_half_the_otp_expiry(
        self, send_otp_email
    ):
        self.owner.generate_totp_secret()
        self.owner.totp_enabled = True
        self.owner.save(update_fields=["totp_secret", "totp_enabled"])
        self.client.force_login(self.owner)
        change_url = reverse(
            "change-totp-authenticator",
            kwargs={"username": self.owner.username},
        )

        def send_test_email(request, purpose):
            user = request.user
            user.otp_code = "123456"
            user.otp_expires_at = timezone.now() + OTP_EXPIRY_DURATION
            user.save(update_fields=["otp_code", "otp_expires_at", "updated_at"])

        send_otp_email.side_effect = send_test_email
        self.client.get(change_url)
        send_otp_email.assert_called_once()

        response = self.client.post(change_url, {"action": "resend_email"})
        self.assertRedirects(response, change_url)
        send_otp_email.assert_called_once()

        session = self.client.session
        session["totp_change_otp_sent_at"] -= (
            OTP_EXPIRY_DURATION.total_seconds() / 2
        ) + 1
        session.save()
        response = self.client.post(change_url, {"action": "resend_email"})
        self.assertRedirects(response, change_url)
        self.assertEqual(send_otp_email.call_count, 2)

    @patch.object(User, "send_otp_email")
    def test_authenticator_change_page_sends_email_code_automatically(
        self, send_otp_email
    ):
        self.owner.generate_totp_secret()
        self.owner.totp_enabled = True
        self.owner.save(update_fields=["totp_secret", "totp_enabled"])
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "change-totp-authenticator",
                kwargs={"username": self.owner.username},
            )
        )

        self.assertEqual(response.status_code, 200)
        send_otp_email.assert_called_once()
        self.assertContains(response, "Email confirmation code")


class OtpEmailMaskingTests(TestCase):
    def test_mask_email_hides_local_part_except_first_character(self):
        self.assertEqual(mask_email("jane.doe@example.com"), "j*******@example.com")

    def test_two_factor_page_displays_only_masked_email(self):
        user = User.object.create_user(
            username="otp_mask_test",
            email="jane.doe@example.com",
            password="A-strong-password-42",
            first_name="Jane",
            last_name="Doe",
            phone_number_code="+1",
            phone_number="5555550199",
            totp_enabled=True,
        )
        session = self.client.session
        session["pending_tfa_user_id"] = user.pk
        session.save()

        response = self.client.get(reverse("totp-verify"))

        self.assertContains(response, "j*******@example.com")
        self.assertNotContains(response, "jane.doe@example.com")

    @patch.object(User, "send_otp_email")
    def test_two_factor_email_otp_notice_displays_only_masked_email(self, send_otp_email):
        user = User.object.create_user(
            username="otp_notice_test",
            email="jane.doe@example.com",
            password="A-strong-password-42",
            first_name="Jane",
            last_name="Doe",
            phone_number_code="+1",
            phone_number="5555550200",
            totp_enabled=True,
        )
        session = self.client.session
        session["pending_tfa_user_id"] = user.pk
        session.save()

        response = self.client.post(reverse("totp-verify"), {"method": "email"})

        send_otp_email.assert_called_once()
        self.assertEqual(send_otp_email.call_args.args[1], "two-factor verification")
        self.assertContains(response, "j*******@example.com")
        self.assertNotContains(response, "jane.doe@example.com")
        self.assertContains(response, 'name="email_code"')
        self.assertNotContains(response, 'name="totp_code"')

    def test_two_factor_page_shows_only_totp_form_by_default(self):
        user = User.object.create_user(
            username="totp_only_test",
            email="totp.only@example.com",
            password="A-strong-password-42",
            first_name="Totp",
            last_name="Only",
            phone_number_code="+1",
            phone_number="5555550201",
            totp_enabled=True,
        )
        session = self.client.session
        session["pending_tfa_user_id"] = user.pk
        session.save()

        response = self.client.get(reverse("totp-verify"))

        self.assertContains(response, 'name="totp_code"')
        self.assertNotContains(response, 'name="email_code"')

    @patch.object(User, "send_otp_email")
    def test_two_factor_defaults_to_email_when_totp_is_disabled(self, send_otp_email):
        user = User.object.create_user(
            username="email_otp_default_test",
            email="email.otp.default@example.com",
            first_name="Email",
            last_name="Default",
            phone_number_code="+1",
            phone_number="5555550203",
        )
        session = self.client.session
        session["pending_tfa_user_id"] = user.pk
        session.save()

        response = self.client.get(reverse("totp-verify"))

        self.assertNotContains(response, 'name="totp_code"')
        self.assertContains(response, 'name="method" value="email"')
        self.assertContains(response, "Send email OTP")

        response = self.client.post(reverse("totp-verify"), {"method": "email"})

        send_otp_email.assert_called_once()
        self.assertEqual(send_otp_email.call_args.args[1], "two-factor verification")
        self.assertContains(response, 'name="email_code"')
        self.assertNotContains(response, 'name="totp_code"')
        self.assertNotContains(response, "Use authenticator code instead")

    @patch.object(User, "send_otp_email")
    @patch.object(User, "verify_otp", return_value=True)
    def test_email_code_verifies_when_totp_is_disabled(
        self, verify_otp, send_otp_email
    ):
        user = User.object.create_user(
            username="email_otp_verify_test",
            email="email.otp.verify@example.com",
            first_name="Email",
            last_name="Verify",
            phone_number_code="+1",
            phone_number="5555550204",
        )
        session = self.client.session
        session["pending_tfa_user_id"] = user.pk
        session.save()

        response = self.client.post(
            reverse("totp-verify"),
            {"email_code": "123456"},
        )

        self.assertRedirects(response, "/")
        verify_otp.assert_called_once_with("123456")
        send_otp_email.assert_not_called()
        self.assertNotIn("pending_tfa_user_id", self.client.session)

    def test_two_factor_can_switch_back_to_totp_form(self):
        user = User.object.create_user(
            username="totp_switch_test",
            email="totp.switch@example.com",
            password="A-strong-password-42",
            first_name="Totp",
            last_name="Switch",
            phone_number_code="+1",
            phone_number="5555550202",
            totp_enabled=True,
        )
        session = self.client.session
        session["pending_tfa_user_id"] = user.pk
        session.save()

        response = self.client.post(reverse("totp-verify"), {"method": "totp"})

        self.assertContains(response, 'name="totp_code"')
        self.assertNotContains(response, 'name="email_code"')

    def test_reset_code_form_masks_email_without_submitting_it(self):
        session = self.client.session
        session["password_reset_email"] = "jane.doe@example.com"
        session.save()

        response = self.client.get(reverse("reset-password"))
        content = response.content.decode()

        self.assertContains(response, "j*******@example.com")
        self.assertNotContains(response, "jane.doe@example.com")
        self.assertNotIn('name="email"', content)
