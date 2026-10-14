import random
from datetime import timedelta

import pyotp
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.mail import send_mail
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from app.settings import DEFAULT_FROM_EMAIL


UsernameValidator = RegexValidator(
    regex=r"^[a-z0-9_]+$",
    message="Invalid username.",
)

NameValidator = RegexValidator(
    regex=r"^[a-zA-Z ]+$",
    message="Invalid name.",
)

PhoneNumberValidator = RegexValidator(
    regex=r"^[0-9]+$",
    message="Invalid phone number.",
)

PhoneNumberCodeValidator = RegexValidator(
    regex=r"^\+[0-9]+$",
    message="Invalid phone number code.",
)


def email_confirmation_expiry():
    return timezone.now() + timedelta(hours=1)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, username=None, email=None, password=None, **extra):
        if not username:
            raise ValueError("The username field must be set.")
        if not email:
            raise ValueError("The email field must be set.")

        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra)
        if password is not None:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username=None, email=None, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        extra.setdefault("role", User.Role.Employee)

        if not extra.get("is_staff"):
            raise ValueError("Superuser must have is_staff=True.")
        if not extra.get("is_superuser"):
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username=username, email=email, password=password, **extra)

    def create(self, **kwargs):
        password = kwargs.pop("password", None)
        user = self.model(**kwargs)
        if password is not None:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        User = "user", "User"
        FrontDeskAgent = "fda", "Front Desk Agent"
        OperationManager = "op-m", "Operation Manager"
        GeneralManager = "gen-m", "General Manager"
        Employee = "employee", "Employee"

    username = models.CharField(max_length=20, unique=True, validators=[UsernameValidator])
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.User)

    phone_number_code = models.CharField(max_length=15, validators=[PhoneNumberCodeValidator])
    phone_number = models.CharField(max_length=20, unique=True, validators=[PhoneNumberValidator])

    email = models.EmailField(unique=True)
    email_confirmed_at = models.DateTimeField(null=True, editable=True)
    email_confirmation_token = models.CharField(max_length=255, null=True, unique=True)
    email_confirmation_expiresat = models.DateTimeField(
        editable=True,
        null=True,
        default=email_confirmation_expiry,
    )

    totp_secret = models.CharField(max_length=64, blank=True, default="")
    totp_enabled = models.BooleanField(default=False)
    otp_code = models.CharField(max_length=6, blank=True, default="")
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    avatar_url = models.CharField(max_length=255, null=True)
    first_name = models.CharField(max_length=100, validators=[NameValidator])
    middle_name = models.CharField(max_length=100, null=True, validators=[NameValidator])
    last_name = models.CharField(max_length=100, validators=[NameValidator])

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_staff = models.BooleanField(null=False, default=False)
    is_superuser = models.BooleanField(null=False, default=False)
    is_active = models.BooleanField(null=False, default=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = [
        "email",
        "phone_number_code",
        "phone_number",
        "first_name",
        "last_name",
    ]

    objects = UserManager()
    object = objects

    def generate_totp_secret(self):
        self.totp_secret = pyotp.random_base32()
        return self.totp_secret

    def generate_otp_code(self):
        code = str(random.randint(100000, 999999))
        self.otp_code = code
        self.otp_expires_at = timezone.now() + timedelta(minutes=10)
        return code

    def verify_otp(self, code):
        if not self.otp_code or not self.otp_expires_at:
            return False
        if timezone.now() > self.otp_expires_at:
            return False
        return str(code).strip() == str(self.otp_code).strip()

    def verify_totp(self, code):
        if not self.totp_secret:
            return False
        return pyotp.TOTP(self.totp_secret).verify(str(code).strip(), valid_window=1)

    def send_otp_email(self, purpose="Login verification"):
        code = self.generate_otp_code()
        self.save(update_fields=["otp_code", "otp_expires_at", "updated_at"])
        send_mail(
            subject=f"ResortEase {purpose}",
            message=f"Your ResortEase security code is {code}. It expires in 10 minutes.",
            from_email=DEFAULT_FROM_EMAIL,
            recipient_list=[self.email],
            fail_silently=False,
        )
        return code

    class Meta:
        db_table = "users"

    @property
    def is_normal_user(self):
        return self.role == self.Role.User

    @property
    def is_user_superuser(self):
        return self.role != self.Role.User and self.is_superuser
