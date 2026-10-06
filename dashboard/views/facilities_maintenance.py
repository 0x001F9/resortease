from django.shortcuts import render
from django.views import View
from django.utils.decorators import method_decorator
from account.decoration.role_required import normal_user_not_allowed
from dashboard.models.branches_facilities import Branch, Facility, Maintenance
from dashboard.decorations.branch_check import check_branch_dashboard


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class FacilitiesMaintenanceView(View):
    def get(self, request):
        branch_model: Branch = request.branch
        facilities = Facility.objects.filter(branch=branch_model)
        maintenance = Maintenance.objects.filter(facility__in=facilities)

        return render(
            request,
            'facilities-maintenance/index.html',
            {
                "facilities": facilities,
                "facilities_count": len(facilities),
                "maintenance": maintenance,
                "maintenance_pending_count": maintenance.filter(status="pending").count()
            }
        )