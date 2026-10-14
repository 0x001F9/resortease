from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.forms import PasswordInput
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import User
from .views.security import mask_email


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

        send_otp_email.assert_called_once_with("two-factor verification")
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
