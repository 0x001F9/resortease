from django.test import TestCase

from .models import User


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
