import secrets
from datetime import timedelta

from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode as django_urlencode
from django.views import View

from account.forms import SignUpForm
from account.redirects import get_safe_next_url
from account.views.security import mask_email
from app.settings import EMAIL_HOST_USER


class SignUpView(View):
    template_name = "account/signup.html"

    def get(self, request):
        next_url = get_safe_next_url(request, request.GET.get("next"))
        if request.user.is_authenticated:
            return redirect(next_url or "home")
        return render(
            request,
            self.template_name,
            {
                "form": SignUpForm(),
                "next": next_url,
                "title": "ResortEase | Sign up",
            },
        )

    def post(self, request):
        next_url = get_safe_next_url(request, request.POST.get("next"))
        if request.user.is_authenticated:
            return redirect(next_url or "home")

        form = SignUpForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "next": next_url,
                    "title": "ResortEase | Sign up",
                },
            )

        user = form.save(commit=False)
        token = secrets.token_urlsafe(32)
        user.email_confirmation_token = token
        user.email_confirmation_expiresat = timezone.now() + timedelta(hours=24)
        user.save()

        verification_url = request.build_absolute_uri(
            reverse("verify-email", kwargs={"token": token})
        )
        if next_url:
            verification_url = (
                f"{verification_url}?{django_urlencode({'next': next_url})}"
            )
        html_content = render_to_string(
            "email/verify_email_addr.html",
            {"action_url": verification_url},
        )
        text_content = render_to_string(
            "email/verify_email_addr.txt",
            {"action_url": verification_url},
        )
        mail = EmailMultiAlternatives(
            subject="Verify your ResortEase email",
            body=text_content,
            from_email=f"ResortEase Security <{EMAIL_HOST_USER}>",
            to=[user.email],
        )
        mail.attach_alternative(html_content, "text/html")
        mail.send()

        return render(
            request,
            "verify_email.html",
            {"masked_email": mask_email(user.email)},
        )
