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
        all_maintenance = Maintenance.objects.filter(facility__in=facilities)
        maintenance = all_maintenance.filter(
            status__in=(Maintenance.Status.PENDING, Maintenance.Status.CANCELLED)
        ).select_related("facility", "issued_by")

        return render(
            request,
            'facilities-maintenance/index.html',
            {
                "facilities": facilities,
                "facilities_count": len(facilities),
                "maintenance": maintenance,
                "maintenance_pending_count": all_maintenance.filter(
                    status=Maintenance.Status.PENDING
                ).count(),
                "maintenance_in_progress_count": all_maintenance.filter(
                    status=Maintenance.Status.IN_PROGRESS
                ).count(),
            }
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class MaintenanceHistoryView(View):
    def get(self, request):
        branch_model: Branch = request.branch
        maintenance = Maintenance.objects.filter(
            facility__branch=branch_model
        ).select_related("facility", "issued_by")

        return render(
            request,
            "facilities-maintenance/history.html",
            {
                "maintenance": maintenance,
                "branch": branch_model,
            },
        )