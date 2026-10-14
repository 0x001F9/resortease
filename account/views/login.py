import secrets

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views import View

from account.models import UsernameValidator


class LoginView(View):
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

        if user.totp_enabled:
            request.session["pending_tfa_user_id"] = user.pk
            return redirect("totp-verify")

        login(request, user)
        messages.success(request, "Welcome back!")
        return redirect("/")
