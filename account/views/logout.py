from django.views import View
from django.shortcuts import redirect
from django.contrib.auth import logout

class LogoutView(View):
    def post(self, request):
        if request.user.is_authenticated:
            logout(request)
        return redirect('/')