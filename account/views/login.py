import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from account.models import User, UsernameValidator
from account.views.security import mask_email
from app import settings
from app.settings import DEFAULT_FROM_EMAIL


class LoginView(View):
    template_verify_email = "verify_email.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")

        return render(request, "login.html")

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("/")

        username = request.POST.get("username")
        password = request.POST.get("password")

        if username is None:
            return render(request, "login.html", {"error": "Username is required."}, status=400)
        if password is None:
            return render(request, "login.html", {"error": "Password is required."}, status=400)

        try:
            UsernameValidator(username or "")
        except ValidationError:
            return render(request, "login.html", {"error": "Invalid username format."}, status=400)

        user = authenticate(request, username=username, password=password)
        if user is None:
            return render(request, "login.html", {"error": "Invalid username or password."}, status=401)

        if user.email_confirmed_at is None:
            now = timezone.now()
            renewal_threshold = now + timedelta(hours=4, minutes=48)
            if (
                user.email_confirmation_expiresat is None
                or user.email_confirmation_expiresat <= renewal_threshold
            ):
                token = secrets.token_urlsafe(32)
                expires_at = now + timedelta(hours=24)
                verification_url = request.build_absolute_uri(
                    reverse("verify-email", kwargs={"token": token})
                )

                html_content = render_to_string(
                    "email/verify_email_addr.html",
                    {
                        "action_url": verification_url,
                    }
                )
                text_content = render_to_string(
                    "email/verify_email_addr.txt",
                    {
                        "action_url": verification_url,
                    }
                )
                mail = EmailMultiAlternatives(
                    subject="Verify your ResortEase email",
                    body=text_content,
                    from_email=f"ResortEase Security <{settings.EMAIL_HOST_USER}>",
                    to=[user.email]
                )
                mail.attach_alternative(html_content, "text/html")
                mail.send()

                user.email_confirmation_token = token
                user.email_confirmation_expiresat = expires_at
                user.save(
                    update_fields=[
                        "email_confirmation_token",
                        "email_confirmation_expiresat",
                        "updated_at",
                    ]
                )

            return render(
                request,
                self.template_verify_email,
                {"masked_email": mask_email(user.email)},
            )

        if user.totp_enabled or user.role != user.Role.User:
            request.session["pending_tfa_user_id"] = user.pk
            return redirect("totp-verify")

        login(request, user)
        messages.success(request, "Welcome back!")
        return redirect("/")


class EmailVerificationView(View):
    def get(self, request, token):
        user = get_object_or_404(User, email_confirmation_token=token)
        if (
            user.email_confirmed_at is not None
            or user.email_confirmation_expiresat is None
            or user.email_confirmation_expiresat <= timezone.now()
        ):
            messages.error(request, "This email verification link has expired.")
            return redirect("login")

        user.email_confirmed_at = timezone.now()
        user.email_confirmation_token = None
        user.email_confirmation_expiresat = None
        user.save(
            update_fields=[
                "email_confirmed_at",
                "email_confirmation_token",
                "email_confirmation_expiresat",
                "updated_at",
            ]
        )
        return render(request, "email_verified.html")
