from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models.branches_facilities import Facility, Maintenance
from dashboard.models.reservations import Payment


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class FacilityDetailView(View):
    template_name = "facilities-maintenance/facility_detail.html"

    def get(self, request, facility_slug):
        facility = get_object_or_404(
            Facility.objects.select_related("branch"),
            branch=request.branch,
            slug=facility_slug,
        )
        repairs = (
            Maintenance.objects.filter(facility=facility)
            .select_related("issued_by")
            .order_by("-reported_at")
        )
        facility_payments = Payment.objects.filter(
            reservation_id__facility=facility
        )
        successful_total = (
            facility_payments.filter(status=Payment.Status.SUCCEEDED)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        refunded_total = (
            facility_payments.filter(status=Payment.Status.REFUNDED)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        total_revenue = max(successful_total - refunded_total, Decimal("0.00"))

        return render(
            request,
            self.template_name,
            {
                "branch": request.branch,
                "facility": facility,
                "repairs": repairs,
                "total_revenue": total_revenue,
                "hide_aside": True,
            },
        )
