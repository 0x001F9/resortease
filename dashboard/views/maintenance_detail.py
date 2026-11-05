from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views import View

from account.models import User
from dashboard.models.branches_facilities import Branch, Maintenance


class MaintenanceDetailView(View):
    template_name = "facilities-maintenance/maintenance_detail.html"

    def get(self, request, branch, maintenance_id):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Authentication is required.")

        branch_model = get_object_or_404(Branch, slug=branch)
        maintenance = get_object_or_404(
            Maintenance.objects.select_related(
                "facility",
                "facility__branch",
                "issued_by",
            ),
            pk=maintenance_id,
            facility__branch=branch_model,
        )
        can_manage_status = (
            request.user.role == User.Role.GeneralManager
            or (
                request.user.role == User.Role.OperationManager
                and branch_model.manager_id_id == request.user.pk
            )
        )
        is_issuer = maintenance.issued_by_id == request.user.pk
        can_edit_details = (
            is_issuer and maintenance.status != Maintenance.Status.COMPLETED
        )
        if not can_manage_status and not is_issuer:
            return HttpResponseForbidden(
                "You are not allowed to view this maintenance request."
            )

        request.branch = branch_model
        request.branches = Branch.objects.all()
        return render(
            request,
            self.template_name,
            {
                "branch": branch_model,
                "maintenance": maintenance,
                "can_manage_status": can_manage_status,
                "can_edit_details": can_edit_details,
                "can_edit": (
                    maintenance.status != Maintenance.Status.COMPLETED
                    and (can_manage_status or can_edit_details)
                ),
                "hide_aside": True
            },
        )
