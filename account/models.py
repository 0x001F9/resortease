import random
import re
from datetime import timedelta

import pyotp
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.mail import send_mail
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from app.settings import EMAIL_HOST_USER
from django.conf import settings

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from app.util.get_info_ip import get_address_ip


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

OTP_EXPIRY_DURATION = timedelta(minutes=10)


def email_confirmation_expiry():
    return timezone.now() + timedelta(hours=24)


def extract_user_request_info(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded_for.split(",")[0].strip() or request.META.get("REMOTE_ADDR")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    operating_system = "Unknown"
    for pattern, name in (
        (r"Windows NT 10\.0", "Windows 10/11"),
        (r"Windows NT 6\.3", "Windows 8.1"),
        (r"Windows NT 6\.2", "Windows 8"),
        (r"Windows NT 6\.1", "Windows 7"),
        (r"Android", "Android"),
        (r"iPhone|iPad|iPod", "iOS"),
        (r"Mac OS X", "macOS"),
        (r"Linux", "Linux"),
    ):
        if re.search(pattern, user_agent, re.IGNORECASE):
            operating_system = name
            break

    browser_name = "Unknown"
    for pattern, name in (
        (r"Edg/", "Microsoft Edge"),
        (r"OPR/|Opera", "Opera"),
        (r"Firefox/", "Firefox"),
        (r"Chrome/", "Chrome"),
        (r"Safari/", "Safari"),
        (r"MSIE |Trident/", "Internet Explorer"),
    ):
        if re.search(pattern, user_agent, re.IGNORECASE):
            browser_name = name
            break

    return {
        "ip_address": ip_address,
        "operating_system": operating_system,
        "browser_name": browser_name,
    }




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
        null=True
    )

    totp_secret = models.CharField(max_length=64, blank=True, default="")
    totp_enabled = models.BooleanField(default=False)
    otp_code = models.CharField(max_length=6, blank=True, default="")
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    avatar_url = models.URLField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=100, validators=[NameValidator])
    middle_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        validators=[NameValidator],
    )
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
        self.otp_expires_at = timezone.now() + OTP_EXPIRY_DURATION
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

    def send_otp_email(self, request, purpose="Login verification"):
        code = self.generate_otp_code()
        self.save(update_fields=["otp_code", "otp_expires_at", "updated_at"])
        req_info = extract_user_request_info(request)

        address_info = get_address_ip(req_info['ip_address'])

        html_content = render_to_string(
            'email/security_code_email.html', 
            {
                'code': code, 
                'purpose': purpose,
                'username': self.username,
                'located_in': address_info or 'Unknown location',
                'ip_address': req_info['ip_address'],
                'operating_system': req_info['operating_system'],
                'browser_name': req_info['browser_name'],
            }
        )

        text_content = render_to_string(
            'email/security_code_email.txt',
            {
                'code': code,
                'purpose': purpose,
                'username': self.username.title(),
                'located_in': address_info or 'Unknown location',
                'ip_address': req_info['ip_address'],
                'operating_system': req_info['operating_system'],
                'browser_name': req_info['browser_name'],
            }
        )

        mail = EmailMultiAlternatives(
            subject=f"ResortEase | {purpose.title()}",
            body=text_content,
            from_email=f"ResortEase Security <{settings.EMAIL_HOST_USER}>",
            to=[self.email]
        )
        mail.attach_alternative(html_content, "text/html")
        mail.send()
        
        return code

    class Meta:
        db_table = "users"

    @property
    def is_normal_user(self):
        return self.role == self.Role.User

    @property
    def is_user_superuser(self):
        return self.role != self.Role.User and self.is_superuser
