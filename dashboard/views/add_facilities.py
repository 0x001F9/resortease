from django.shortcuts import redirect, render
from django.views import View
from django.utils.decorators import method_decorator
from account.decoration.role_required import normal_user_not_allowed
from dashboard.models.branches_facilities import Branch, Facility, Maintenance
from dashboard.decorations.branch_check import check_branch_dashboard


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class AddFacilitiesMaintenanceView(View):
    def get_context_data(self, request, form_data=None, errors=None):
        return {
            "facilities": Facility.objects.filter(
                branch=request.branch
            ).order_by("name"),
            "form_data": form_data or {},
            "errors": errors or {},
        }

    def get(self, request):
        return render(
            request,
            'facilities-maintenance/add_maintenance.html',
            self.get_context_data(request),
        )

    def post(self, request):
        facilities = Facility.objects.filter(branch=request.branch)
        facility_id = request.POST.get("facility", "")
        facility = (
            facilities.filter(pk=facility_id).first()
            if facility_id.isdecimal()
            else None
        )

        form_data = {
            "facility": facility_id,
            "title": request.POST.get("title", "").strip(),
            "issue_type": request.POST.get("issue_type", "").strip(),
            "priority": request.POST.get("priority", Maintenance.Priority.MEDIUM),
            "description": request.POST.get("description", "").strip(),
        }
        errors = {}

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
        if form_data["priority"] not in Maintenance.Priority.values:
            errors["priority"] = "Select a valid priority."
        if not form_data["description"]:
            errors["description"] = "Describe the maintenance issue."

        if errors:
            return render(
                request,
                "facilities-maintenance/add_maintenance.html",
                self.get_context_data(request, form_data, errors),
            )

        Maintenance.objects.create(
            facility=facility,
            title=form_data["title"],
            issue_type=form_data["issue_type"],
            priority=form_data["priority"],
            description=form_data["description"],
            issued_by=request.user,
        )
        return redirect(
            f"/dashboard/{request.branch.slug}/facilities-and-maintenance/"
        )