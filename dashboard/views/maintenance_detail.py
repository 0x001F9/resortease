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
        is_manager = (
            request.user.role
            in (User.Role.OperationManager, User.Role.GeneralManager)
            and branch_model.manager_id_id == request.user.pk
        )
        can_manage = is_manager or request.user.is_user_superuser
        is_issuer = maintenance.issued_by_id == request.user.pk
        can_edit_details = is_issuer and maintenance.status == Maintenance.Status.PENDING
        if not can_manage and not is_issuer:
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
                "can_manage": can_manage,
                "can_edit_details": can_edit_details,
                "hide_aside": True
            },
        )
