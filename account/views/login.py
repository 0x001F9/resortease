import secrets

from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import authenticate, login
from account.models import UsernameValidator
from django.core.exceptions import ValidationError

class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/')

        return render(request, 'login.html')

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('/')

        username = request.POST.get('username')
        password = request.POST.get('password')

        if username is None:
            return render(request, 'login.html', {'error': 'Username is required.'}, status=400)
        elif password is None:
            return render(request, 'login.html', {'error': 'Password is required.'}, status=400)

        try:
            UsernameValidator(username or '')
        except ValidationError:
            return render(request, 'login.html', {'error': 'Invalid username format.'}, status=400)

        # Authenticate the user
        user = authenticate(request, username=username, password=password)

        if user is None:
            return render(request, 'login.html', {'error': 'Invalid username or password.'}, status=401)

        login(request, user)

        return redirect('/')