from functools import wraps
from dashboard.models.branches_facilities import Branch
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404

def check_branch_dashboard(view_func):
    @wraps(view_func)
    def wrapper(request, branch, *args, **kwrags):
        branches = Branch.objects.filter()

        if branches is None or len(branches) <= 0:
            return Http404()
        
        if not request.user.is_user_superuser:
            return HttpResponseForbidden()

        request.branch = get_object_or_404(Branch, slug=branch)
        request.branches = branches
        return view_func(request, *args, **kwrags)
    return wrapper
