from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from account.forms import ProfileForm
from account.models import User


@method_decorator(login_required(login_url="login"), name="dispatch")
class UserProfileView(View):
    def get(self, request, username):
        profile_user = get_object_or_404(User, username=username)
        is_owner = request.user.pk == profile_user.pk
        if request.user.is_normal_user and not is_owner:
            return HttpResponseForbidden("You are not allowed to view this profile.")

        reservations = profile_user.reservations.select_related(
            "facility",
            "calendar_entry",
        ).order_by("-starts_at")

        return render(
            request,
            "account/profile.html",
            {
                "profile_user": profile_user,
                "is_owner": is_owner,
                "full_name": " ".join(
                    part
                    for part in (
                        profile_user.first_name,
                        profile_user.middle_name,
                        profile_user.last_name,
                    )
                    if part
                ),
                "reservations": reservations,
            },
        )


@method_decorator(login_required(login_url="login"), name="dispatch")
class UserSettingsView(View):
    def get(self, request, username):
        return self._handle(request, username)

    def post(self, request, username):
        return self._handle(request, username)

    def _handle(self, request, username):
        profile_user = get_object_or_404(User, username=username)
        if request.user.pk != profile_user.pk:
            return HttpResponseForbidden(
                "You are not allowed to change these settings."
            )

        form = ProfileForm(
            request.POST if request.method == "POST" else None,
            instance=profile_user,
        )
        if request.method == "POST" and form.is_valid():
            form.save()
            return redirect(
                reverse("user-profile", kwargs={"username": profile_user.username})
            )

        return render(
            request,
            "account/profile_settings.html",
            {
                "profile_user": profile_user,
                "form": form,
            },
        )