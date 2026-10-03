from django.shortcuts import render
from django.views import View
from django.utils.decorators import method_decorator
from account.decoration.role_required import normal_user_not_allowed

@method_decorator(normal_user_not_allowed, name="dispatch")
class DashboardView(View):
    def get(self, request):
        return render(request,'dashboard.html')