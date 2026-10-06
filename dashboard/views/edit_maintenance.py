from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from account.models import User
from dashboard.models.branches_facilities import Branch, Facility, Maintenance


class EditFacilitiesMaintenanceView(View):
    template_name = "facilities-maintenance/edit_maintenance.html"

    def get_request_context(self, request, branch_slug, maintenance_id):
        if not request.user.is_authenticated:
            return None

        branch = get_object_or_404(Branch, slug=branch_slug)
        request.branch = branch
        request.branches = Branch.objects.all()
        maintenance = get_object_or_404(
            Maintenance.objects.select_related("facility", "issued_by"),
            pk=maintenance_id,
            facility__branch=branch,
        )

        is_manager = (
            request.user.role
            in (User.Role.OperationManager, User.Role.GeneralManager)
            and branch.manager_id_id == request.user.pk
        )
        can_manage = is_manager or request.user.is_user_superuser
        can_edit_details = (
            maintenance.issued_by_id == request.user.pk
            and maintenance.status == Maintenance.Status.PENDING
        )
        if not can_manage and not can_edit_details:
            return None

        return {
            "branch": branch,
            "maintenance": maintenance,
            "facilities": Facility.objects.filter(branch=branch).order_by("name"),
            "can_manage": can_manage,
            "can_edit_details": can_edit_details,
            "form_data": {
                "facility": str(maintenance.facility_id),
                "title": maintenance.title,
                "issue_type": maintenance.issue_type,
                "description": maintenance.description,
                "priority": maintenance.priority,
                "status": maintenance.status,
            },
            "errors": {},
            "hide_aside": True
        }

    def get(self, request, branch, maintenance_id):
        context = self.get_request_context(request, branch, maintenance_id)
        if context is None:
            return HttpResponseForbidden("You are not allowed to edit this request.")

        return render(request, self.template_name, context)

    def post(self, request, branch, maintenance_id):
        context = self.get_request_context(request, branch, maintenance_id)
        if context is None:
            return HttpResponseForbidden("You are not allowed to edit this request.")

        maintenance = context["maintenance"]
        form_data = {
            "facility": str(maintenance.facility_id),
            "title": maintenance.title,
            "issue_type": maintenance.issue_type,
            "description": maintenance.description,
            "priority": maintenance.priority,
            "status": maintenance.status,
        }
        errors = {}

        if context["can_edit_details"]:
            form_data.update({
                "facility": request.POST.get("facility", "").strip(),
                "title": request.POST.get("title", "").strip(),
                "issue_type": request.POST.get("issue_type", "").strip(),
                "description": request.POST.get("description", "").strip(),
            })
            facility_id = form_data["facility"]
            facility = (
                context["facilities"].filter(pk=facility_id).first()
                if facility_id.isdecimal()
                else None
            )
            if facility is None:
                errors["facility"] = "Select a facility in this branch."
            if not form_data["title"]:
                errors["title"] = "Enter a request title."
            elif len(form_data["title"]) > 200:
                errors["title"] = "The title must be 200 characters or fewer."
            if not form_data["issue_type"]:
                errors["issue_type"] = "Enter an issue type."
            elif len(form_data["issue_type"]) > 80:
                errors["issue_type"] = "The issue type must be 80 characters or fewer."
            if not form_data["description"]:
                errors["description"] = "Describe the maintenance issue."
        else:
            facility = maintenance.facility

        if context["can_manage"]:
            form_data["priority"] = request.POST.get("priority", "").strip()
            form_data["status"] = request.POST.get("status", "").strip()
            if form_data["priority"] not in Maintenance.Priority.values:
                errors["priority"] = "Select a valid priority."
            if form_data["status"] not in Maintenance.Status.values:
                errors["status"] = "Select a valid status."

        if errors:
            context["form_data"] = form_data
            context["errors"] = errors
            return render(request, self.template_name, context)

        if context["can_edit_details"]:
            maintenance.facility = facility
            maintenance.title = form_data["title"]
            maintenance.issue_type = form_data["issue_type"]
            maintenance.description = form_data["description"]
        if context["can_manage"]:
            maintenance.priority = form_data["priority"]
            maintenance.status = form_data["status"]
        maintenance.save()

        return redirect(
            f"/dashboard/{context['branch'].slug}/facilities-and-maintenance/"
        )
