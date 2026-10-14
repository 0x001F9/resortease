from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.forms import PasswordInput
from django.test import TestCase

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import User


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
