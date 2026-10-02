import secrets

from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import authenticate, login
from account.models import MFASession, User
from account.models import UsernameValidator
from django.core.exceptions import ValidationError

class LoginView(View):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
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

        if not user.is_2fa_enabled:
            login(request, user)
            return redirect('/')

        # if user has 2fa enabled:
        mfa = MFASession.objects.create(
            user=user,
            type=MFASession.TypeMFA.Email,
            purpose=MFASession.PurposeMFA.Login,
            session=secrets.token_urlsafe(32),
            mfa_code=MFASession.generate_mfa_code()
        )
        
        return redirect('/verify_mfa/' + mfa.session)