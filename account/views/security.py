import base64
import io
import math

import pyotp
import qrcode
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST

from account.models import OTP_EXPIRY_DURATION, User


def mask_email(email: str) -> str:
    local_part, separator, domain = email.partition("@")
    if not separator:
        return "*" * 5
    return f"{local_part[:1]}{'*' * 6}@{domain}"


def build_qr_code_data_url(value):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"


class TOTPSetupView(View):
    template_name = "totp_setup.html"

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect("login")

        if request.user.totp_enabled:
            messages.error(
                request,
                "TOTP is already enabled for your account.",
            )
            return redirect("user-settings", username=request.user.username)

        request.user.generate_totp_secret()
        request.user.save(update_fields=["totp_secret", "updated_at"])
        secret = request.user.totp_secret
        totp = pyotp.TOTP(secret)
        otpauth_url = totp.provisioning_uri(
            name=request.user.email,
            issuer_name="ResortEase",
        )
        return render(
            request,
            self.template_name,
            {
                "title": "ResortEase | Setup TOTP",
                "secret": secret,
                "otpauth_url": otpauth_url,
                "qr_code_data_url": build_qr_code_data_url(otpauth_url),
            },
        )

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect("login")

        if request.user.totp_enabled:
            return redirect(
                "user-settings",
                username=request.user.username,
            )

        code = (request.POST.get("code") or "").strip()
        secret = request.user.totp_secret
        if not secret:
            request.user.generate_totp_secret()
            request.user.save(update_fields=["totp_secret", "updated_at"])
            secret = request.user.totp_secret

        if pyotp.TOTP(secret).verify(code, valid_window=1):
            request.user.totp_enabled = True
            request.user.save(update_fields=["totp_enabled", "updated_at"])
            messages.success(request, "TOTP has been enabled for your account.")
            return redirect("user-settings", username=request.user.username)

        totp = pyotp.TOTP(secret)
        otpauth_url = totp.provisioning_uri(
            name=request.user.email,
            issuer_name="ResortEase",
        )
        return render(
            request,
            self.template_name,
            {
                "title": "ResortEase | Setup TOTP",
                "secret": secret,
                "otpauth_url": otpauth_url,
                "qr_code_data_url": build_qr_code_data_url(otpauth_url),
                "error": "The verification code was invalid or has expired.",
            },
        )


def clear_totp_change_session(request):
    for key in (
        "totp_change_email_user_id",
        "totp_change_setup_user_id",
        "totp_change_setup_secret",
        "totp_change_otp_sent_at",
        "totp_change_error",
        "totp_change_success",
    ):
        request.session.pop(key, None)


def totp_change_context(request, user):
    setup_confirmed = (
        request.session.get("totp_change_setup_user_id") == user.pk
    )
    context = {
        "title": "ResortEase | Change authenticator",
        "setup_confirmed": setup_confirmed,
    }
    if setup_confirmed:
        secret = request.session.get("totp_change_setup_secret")
        if not secret:
            secret = pyotp.random_base32()
            request.session["totp_change_setup_secret"] = secret
        otpauth_url = pyotp.TOTP(secret).provisioning_uri(
            name=user.email,
            issuer_name="ResortEase",
        )
        context.update(
            {
                "qr_code_data_url": build_qr_code_data_url(otpauth_url),
                "secret": secret,
            }
        )
        return context

    sent_at = request.session.get("totp_change_otp_sent_at")
    cooldown_seconds = math.ceil(OTP_EXPIRY_DURATION.total_seconds() / 2)
    seconds_until_resend = 0
    if sent_at is not None:
        elapsed = timezone.now().timestamp() - sent_at
        seconds_until_resend = max(
            0,
            math.ceil(cooldown_seconds - elapsed),
        )
    context.update(
        {
            "masked_email": mask_email(user.email),
            "seconds_until_resend": seconds_until_resend,
        }
    )
    return context


@login_required(login_url="login")
def change_totp_authenticator(request, username):
    if request.user.username != username:
        return HttpResponseForbidden("You are not allowed to change these settings.")
    if not request.user.totp_enabled:
        messages.error(request, "Enable TOTP before changing your authenticator.")
        return redirect("user-settings", username=request.user.username)

    user = request.user
    email_user_id = request.session.get("totp_change_email_user_id")
    setup_user_id = request.session.get("totp_change_setup_user_id")
    if email_user_id not in (None, user.pk):
        clear_totp_change_session(request)
        email_user_id = None
    if setup_user_id not in (None, user.pk):
        clear_totp_change_session(request)
        setup_user_id = None

    if request.method == "GET":
        if setup_user_id != user.pk:
            code_is_valid = (
                user.otp_expires_at is not None
                and user.otp_expires_at > timezone.now()
                and bool(user.otp_code)
                and email_user_id == user.pk
            )
            if not code_is_valid:
                user.send_otp_email(request, "authenticator change confirmation")
                request.session["totp_change_email_user_id"] = user.pk
                request.session["totp_change_otp_sent_at"] = timezone.now().timestamp()
        context = totp_change_context(request, user)
        context["error"] = request.session.pop("totp_change_error", None)
        context["success"] = request.session.pop("totp_change_success", None)
        return render(request, "account/totp_change.html", context)

    if request.method != "POST":
        return HttpResponseForbidden("Unsupported request method.")

    action = request.POST.get("action")
    if action == "cancel":
        if email_user_id == user.pk:
            user.otp_code = ""
            user.otp_expires_at = None
            user.save(
                update_fields=["otp_code", "otp_expires_at", "updated_at"]
            )
        clear_totp_change_session(request)
        messages.info(request, "Authenticator change cancelled.")
        return redirect("user-settings", username=user.username)

    if action == "resend_email":
        if setup_user_id == user.pk or email_user_id != user.pk:
            return HttpResponseForbidden("No authenticator change was requested.")
        context = totp_change_context(request, user)
        if context["seconds_until_resend"] > 0:
            request.session["totp_change_error"] = (
                "Please wait before requesting another email code."
            )
        else:
            user.send_otp_email(request, "authenticator change confirmation")
            request.session["totp_change_otp_sent_at"] = timezone.now().timestamp()
            request.session["totp_change_success"] = (
                f"A new code was sent to {user.email}."
            )
        return redirect("change-totp-authenticator", username=user.username)

    if action == "confirm_email":
        if setup_user_id == user.pk or email_user_id != user.pk:
            return HttpResponseForbidden("No authenticator change was requested.")
        email_code = (request.POST.get("email_code") or "").strip()
        if not user.verify_otp(email_code):
            request.session["totp_change_error"] = (
                "The email code was invalid or has expired."
            )
            return redirect("change-totp-authenticator", username=user.username)

        user.otp_code = ""
        user.otp_expires_at = None
        user.save(update_fields=["otp_code", "otp_expires_at", "updated_at"])
        request.session.pop("totp_change_email_user_id", None)
        request.session.pop("totp_change_otp_sent_at", None)
        request.session["totp_change_setup_user_id"] = user.pk
        request.session["totp_change_setup_secret"] = pyotp.random_base32()
        request.session["totp_change_success"] = (
            "Email confirmed. Set up your new authenticator."
        )
        return redirect("change-totp-authenticator", username=user.username)

    if action == "verify_totp":
        if setup_user_id != user.pk:
            return HttpResponseForbidden("Confirm your email before setting up TOTP.")
        secret = request.session.get("totp_change_setup_secret")
        code = (request.POST.get("totp_code") or "").strip()
        if not secret or not pyotp.TOTP(secret).verify(code, valid_window=1):
            request.session["totp_change_error"] = (
                "The authenticator code was invalid or expired."
            )
            return redirect("change-totp-authenticator", username=user.username)

        user.totp_secret = secret
        user.totp_enabled = True
        user.save(update_fields=["totp_secret", "totp_enabled", "updated_at"])
        clear_totp_change_session(request)
        messages.success(request, "Your authenticator app has been changed.")
        return redirect("user-settings", username=user.username)

    return HttpResponseForbidden("Invalid authenticator change action.")


@login_required(login_url="login")
@require_POST
def update_totp_settings(request, username):
    if request.user.username != username:
        return HttpResponseForbidden("You are not allowed to change these settings.")

    action = request.POST.get("action")
    if action != "disable":
        return HttpResponseForbidden("Invalid TOTP settings action.")

    if not request.user.totp_enabled:
        messages.error(request, "TOTP is not enabled for your account.")
        return redirect("user-settings", username=request.user.username)

    code = (request.POST.get("totp_code") or "").strip()
    if not request.user.verify_totp(code):
        messages.error(request, "The authenticator code was invalid or has expired.")
        return redirect("user-settings", username=request.user.username)

    if action == "disable":
        if request.session.get("totp_change_email_user_id") == request.user.pk:
            request.user.otp_code = ""
            request.user.otp_expires_at = None
            request.user.save(
                update_fields=["otp_code", "otp_expires_at", "updated_at"]
            )
        clear_totp_change_session(request)
        request.user.totp_enabled = False
        request.user.totp_secret = ""
        request.user.save(
            update_fields=["totp_enabled", "totp_secret", "updated_at"]
        )
        messages.success(request, "TOTP has been turned off for your account.")
        return redirect("user-settings", username=request.user.username)


class TOTPVerificationView(View):
    template_name = "totp_verify.html"
    template_verify_email = "verify_email.html"

    def get_user_from_session(self, request):
        user_id = request.session.get("pending_tfa_user_id")
        if not user_id:
            return None
        try:
            return User.object.get(pk=user_id)
        except User.DoesNotExist:
            return None

    def clear_pending_login(self, request):
        request.session.pop("pending_tfa_user_id", None)

    def get(self, request):
        user = self.get_user_from_session(request)
        if user is None:
            return redirect("login")
        return render(
            request,
            self.template_name,
            {
                "user": user,
                "masked_email": mask_email(user.email),
                "can_use_totp": user.totp_enabled,
            },
        )

    def post(self, request):
        user = self.get_user_from_session(request)
        if user is None:
            return redirect("login")

        is_user_enabled_totp = user.totp_enabled
        totp_code = (request.POST.get("totp_code") or "").strip()
        email_code = (request.POST.get("email_code") or "").strip()

        if not email_code and (
            not is_user_enabled_totp or request.POST.get("method") == "email"
        ):
            user.send_otp_email(request, "two-factor verification")
            messages.info(request, "A security code has been sent to your email.")
            return render(
                request,
                self.template_name,
                {
                    "user": user,
                    "masked_email": mask_email(user.email),
                    "sent_email_otp": True,
                    "can_use_totp": is_user_enabled_totp,
                },
            )

        if request.POST.get("method") == "totp" and is_user_enabled_totp:
            return render(
                request,
                self.template_name,
                {
                    "user": user,
                    "masked_email": mask_email(user.email),
                    "can_use_totp": is_user_enabled_totp,
                },
            )

        if is_user_enabled_totp and totp_code and user.verify_totp(totp_code):
            self.clear_pending_login(request)
            login(request, user)
            return redirect("/")

        if email_code and user.verify_otp(email_code):
            self.clear_pending_login(request)
            login(request, user)

            if not is_user_enabled_totp:
                messages.info(
                    request,
                    "You have successfully logged in. For enhanced security, consider enabling TOTP.",
                )
                return redirect("totp-setup")

            return redirect("/")

        if email_code:
            return render(
                request,
                self.template_name,
                {
                    "user": user,
                    "masked_email": mask_email(user.email),
                    "sent_email_otp": True,
                    "error": "The verification code was invalid or expired.",
                    "can_use_totp": is_user_enabled_totp,
                },
            )

        return render(
            request,
            self.template_name,
            {
                "user": user,
                "masked_email": mask_email(user.email),
                "error": "The verification code was invalid or expired.",
                "can_use_totp": is_user_enabled_totp,
            },
        )


class PasswordResetRequestView(View):
    template_name = "forgot_password.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = (request.POST.get("email") or "").strip().lower()
        if not email:
            return render(
                request,
                self.template_name,
                {"error": "Please enter the email address linked to your account."},
            )

        user = User.object.filter(email__iexact=email).first()
        if user is not None:
            user.send_otp_email(request, "password reset")
            request.session["password_reset_email"] = user.email
            return redirect("reset-password")

        request.session["password_reset_email"] = email
        return redirect("reset-password")


class PasswordResetConfirmView(View):
    template_name = "reset_password.html"

    def get(self, request):
        email = request.session.get("password_reset_email")
        if not email:
            return redirect("forgot-password")
        return render(
            request,
            self.template_name,
            {"masked_email": mask_email(email)},
        )

    def post(self, request):
        email = request.session.get("password_reset_email")
        if not email:
            return redirect("forgot-password")

        code = (request.POST.get("otp_code") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        masked_email = mask_email(email)

        user = User.object.filter(email__iexact=email).first()
        if user is None:
            return render(
                request,
                self.template_name,
                {
                    "masked_email": masked_email,
                    "error": "We could not find an account with that email address.",
                },
            )

        if not user.verify_otp(code):
            return render(
                request,
                self.template_name,
                {
                    "masked_email": masked_email,
                    "error": "The OTP code is invalid or has expired.",
                },
            )

        if password != confirm_password:
            return render(
                request,
                self.template_name,
                {
                    "masked_email": masked_email,
                    "error": "The new passwords do not match.",
                },
            )

        if len(password) < 8:
            return render(
                request,
                self.template_name,
                {
                    "masked_email": masked_email,
                    "error": "Password must be at least 8 characters long.",
                },
            )

        user.set_password(password)
        user.otp_code = ""
        user.otp_expires_at = None
        user.save(update_fields=["password", "otp_code", "otp_expires_at", "updated_at"])

        request.session.pop("password_reset_email", None)
        messages.success(request, "Your password has been reset successfully.")
        return redirect("login")
