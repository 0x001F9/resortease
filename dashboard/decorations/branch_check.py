from functools import wraps

from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404

from account.models import User
from dashboard.models.branches_facilities import Branch


def check_branch_dashboard(view_func):
    @wraps(view_func)
    def wrapper(request, branch, *args, **kwrags):
        if not request.user.is_authenticated:
            return HttpResponseForbidden()

        request.branch = get_object_or_404(Branch, slug=branch)
        if (
            request.user.is_user_superuser
            or request.user.role == User.Role.GeneralManager
        ):
            request.branches = Branch.objects.order_by("name")
        elif request.user.role == User.Role.OperationManager:
            request.branches = Branch.objects.filter(manager_id=request.user).order_by(
                "name"
            )
            if not request.branches.filter(pk=request.branch.pk).exists():
                raise Http404
        else:
            return HttpResponseForbidden()

        return view_func(request, *args, **kwrags)

    return wrapper
