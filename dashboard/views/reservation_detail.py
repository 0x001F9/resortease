from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Reservation


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class ReservationDetailView(View):
    template_name = "reservations/detail.html"

    def get(self, request, reservation_id, *args, **kwargs):
        reservation = get_object_or_404(
            Reservation.objects.select_related(
                "guest",
                "facility",
                "calendar_entry__facility",
            ).prefetch_related("calendar_entry__payments"),
            pk=reservation_id,
            facility__branch=request.branch,
        )
        return render(
            request,
            self.template_name,
            {
                "reservation": reservation,
                "calendar_entry": getattr(reservation, "calendar_entry", None),
                "hide_aside": True,
            },
        )
