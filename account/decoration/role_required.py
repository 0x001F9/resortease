from functools import wraps
from django.http import HttpResponseForbidden

def role_required(*allowed_roles):
    def decorators(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwrags):
            if not request.user.is_authenticated:
                return HttpResponseForbidden("Authentication on required.")

            if request.user.role not in allowed_roles:
                return HttpResponseForbidden("You are not allowed to do that.")

            return view_func(request, *args, **kwrags)
        return wrapper
    return decorators

def normal_user_not_allowed(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwrags):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Authentication on required.")

        if request.user.is_normal_user:
            return HttpResponseForbidden("You are not allowed to do that.")

        return view_func(request, *args, **kwrags)
    return wrapper
