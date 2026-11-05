from functools import wraps

from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from account.models import User
from dashboard.models.branches_facilities import Branch


def financial_reports_access_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if (
            not request.user.is_authenticated
            or not request.user.can_view_financial_reports
        ):
            return HttpResponseForbidden()
        return view_func(request, *args, **kwargs)

    return wrapper


def check_branch_dashboard(view_func):
    @wraps(view_func)
    def wrapper(request, branch, *args, **kwrags):
        if not request.user.is_authenticated:
            return HttpResponseForbidden()

        if (
            request.user.is_user_superuser
            or request.user.role == User.Role.GeneralManager
        ):
            request.branch = get_object_or_404(Branch, slug=branch)
            request.branches = Branch.objects.order_by("name")
        elif request.user.role == User.Role.OperationManager:
            request.branches = Branch.objects.filter(manager_id=request.user).order_by(
                "name"
            )
            try:
                request.branch = request.branches.get(slug=branch)
            except Branch.DoesNotExist:
                if not request.branches.exists():
                    return render(request, "employee_branch_unassigned.html")
                raise Http404
        elif request.user.role in (
            User.Role.Employee,
            User.Role.FrontDeskAgent,
        ):
            if request.user.assigned_branch_id is None:
                return render(request, "employee_branch_unassigned.html")
            request.branch = get_object_or_404(
                Branch,
                slug=branch,
                pk=request.user.assigned_branch_id,
            )
            request.branches = Branch.objects.filter(pk=request.branch.pk)
        else:
            return HttpResponseForbidden()

        return view_func(request, *args, **kwrags)

    return wrapper
