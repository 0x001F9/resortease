import base64
import io

import pyotp
import qrcode
from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.views import View

from account.models import User


def mask_email(email):
    local_part, separator, domain = email.partition("@")
    if not separator:
        return "*" * max(len(email), 3)
    return f"{local_part[:1]}{'*' * max(len(local_part) - 1, 3)}@{domain}"


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

        if not request.user.totp_secret:
            request.user.generate_totp_secret()
            request.user.save(update_fields=["totp_secret", "updated_at"])

        totp = pyotp.TOTP(request.user.totp_secret)
        otpauth_url = totp.provisioning_uri(
            name=request.user.email,
            issuer_name="ResortEase",
        )
        return render(
            request,
            self.template_name,
            {
                "secret": request.user.totp_secret,
                "otpauth_url": otpauth_url,
                "qr_code_data_url": build_qr_code_data_url(otpauth_url),
            },
        )

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect("login")

        code = (request.POST.get("code") or "").strip()
        if not request.user.totp_secret:
            request.user.generate_totp_secret()
            request.user.save(update_fields=["totp_secret", "updated_at"])

        if request.user.verify_totp(code):
            request.user.totp_enabled = True
            request.user.save(update_fields=["totp_enabled", "updated_at"])
            messages.success(request, "TOTP has been enabled for your account.")
            return redirect("/")

        totp = pyotp.TOTP(request.user.totp_secret)
        otpauth_url = totp.provisioning_uri(
            name=request.user.email,
            issuer_name="ResortEase",
        )
        return render(
            request,
            self.template_name,
            {
                "secret": request.user.totp_secret,
                "otpauth_url": otpauth_url,
                "qr_code_data_url": build_qr_code_data_url(otpauth_url),
                "error": "The verification code was invalid or has expired.",
            },
        )


class TOTPVerificationView(View):
    template_name = "totp_verify.html"

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
                "can_use_email_fallback": user.totp_enabled,
            },
        )

    def post(self, request):
        user = self.get_user_from_session(request)
        if user is None:
            return redirect("login")

        totp_code = (request.POST.get("totp_code") or "").strip()
        email_code = (request.POST.get("email_code") or "").strip()
        send_email_otp = request.POST.get("method") == "email"

        if send_email_otp:
            user.send_otp_email("two-factor verification")
            messages.info(request, "A security code has been sent to your email.")
            return render(
                request,
                self.template_name,
                {
                    "user": user,
                    "masked_email": mask_email(user.email),
                    "sent_email_otp": True,
                },
            )

        if request.POST.get("method") == "totp":
            return render(
                request,
                self.template_name,
                {
                    "user": user,
                    "masked_email": mask_email(user.email),
                },
            )

        if totp_code and user.verify_totp(totp_code):
            self.clear_pending_login(request)
            login(request, user)
            return redirect("/")

        if email_code and user.verify_otp(email_code):
            self.clear_pending_login(request)
            login(request, user)
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
                },
            )

        return render(
            request,
            self.template_name,
            {
                "user": user,
                "masked_email": mask_email(user.email),
                "error": "The verification code was invalid or expired.",
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
            user.send_otp_email("password reset")
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
