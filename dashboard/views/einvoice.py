from django.http import Http404
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from app.invoices import einvoice_pdf_response
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models import Calendar, Reservation


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class ReservationEInvoiceDownloadView(View):
    def get(self, request, reservation_id, *args, **kwargs):
        reservation = Reservation.objects.select_related(
            "guest",
            "facility__branch",
            "calendar_entry",
        ).filter(
            pk=reservation_id,
            facility__branch=request.branch,
        ).first()
        if reservation is None:
            raise Http404
        if reservation.current_status != Calendar.Status.CONFIRMED:
            raise Http404

        return einvoice_pdf_response(reservation)
