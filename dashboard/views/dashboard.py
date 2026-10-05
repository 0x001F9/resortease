from django.shortcuts import render, redirect
from django.views import View
from django.utils.decorators import method_decorator
from account.decoration.role_required import normal_user_not_allowed
from dashboard.models import Branch
from dashboard.decorations.branch_check import check_branch_dashboard

@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class DashboardView(View):
    def get(self, request):
        return render(request,'dashboard.html')

@method_decorator(normal_user_not_allowed, name="dispatch")
class DashboardRedirectView(View):
    def get(self, request):
        branch = Branch.objects.first()

        if branch is None:
            return render(request,'branch_null.html')

        return redirect(f'/dashboard/{branch.slug}')