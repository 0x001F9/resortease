import secrets

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from datetime import timedelta


UsernameValidator = RegexValidator(
    regex=r'^[a-z0-9_]+$',
    message="Invalid username."
)

NameValidator = RegexValidator(
    regex=r'^[a-zA-Z]+$',
    message="Invalid name."
)

PhoneNumberValidator = RegexValidator(
    regex=r'^[0-9]+$',
    message="Invalid phone number."
)

PhoneNumberCodeValidator = RegexValidator(
    regex=r'^\+[0-9]+$',
    message="Invalid phone number code."
)

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)

        return user
    
    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        extra.setdefault('is_active', True)
        extra.setdefault('role', User.Role.Employee)

        return self.create_user(email=email,  password=password, **extra)

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
    email_confirmation_expiresat = models.DateTimeField(editable=True, null=True, default=timezone.now() + timedelta(hours=1))

    avatar_url = models.CharField(max_length=255, null=True)
    first_name = models.CharField(max_length=100, validators=[NameValidator])
    middle_name = models.CharField(max_length=100, validators=[NameValidator])
    last_name = models.CharField(max_length=100, validators=[NameValidator])

    totp_secret = models.CharField(max_length=255, null=True)
    is_2fa_enabled = models.BooleanField(null=False, default=False)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # for admin portal
    is_staff = models.BooleanField(null=False, default=False)
    is_superuser = models.BooleanField(null=False, default=False)
    is_active = models.BooleanField(null=False, default=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = [
        'phone_number_code',
        'phone_number',
        'email',
        'first_name',
        'last_name',
    ]
    object = UserManager()

    class Meta:
        db_table = "users"

# mfa session table
class MFASession(models.Model):
    class TypeMFA(models.TextChoices):
        Email = "email", "Email"
        TOTP = "totp", "TOTP"

    class PurposeMFA(models.TextChoices):
        Login = "login", "Login"
        ResetPassword = "reset-password", "Reset Password"
        ChangeEmail = "change-email", "Change Email"
        ChangePhoneNumber = "change-phone-number", "Change Phone Number"
        Sudo = "sudo", "Sudo"
    
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=10, choices=TypeMFA.choices)
    purpose = models.CharField(max_length=30, choices=PurposeMFA.choices)
    mfa_code = models.CharField(max_length=6)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=timezone.now() + timedelta(minutes=5))
    
    class Meta:
        db_table = "mfa_sessions"

    def generate_mfa_code():
        import secrets, string
        digits = string.digits 
        return ''.join(secrets.choice(digits) for _ in range(6))

    