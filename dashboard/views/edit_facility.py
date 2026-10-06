from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models.branches_facilities import Facility


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class EditFacilityView(View):
    template_name = "facilities-maintenance/edit_facility.html"

    def get_facility(self, request, facility_slug):
        return get_object_or_404(
            Facility,
            branch=request.branch,
            slug=facility_slug,
        )

    def get_context(self, request, facility, form_data=None, errors=None):
        return {
            "branch": request.branch,
            "facility": facility,
            "facility_types": Facility.FacilityType.choices,
            "facility_statuses": Facility.FacilityStatus.choices,
            "form_data": form_data or {
                "name": facility.name,
                "facility_type": facility.facility_type,
                "description": facility.description,
                "status": facility.status,
                "capacity": facility.capacity,
                "notes": facility.notes,
            },
            "errors": errors or {},
            "hide_aside": True,
        }

    def get(self, request, facility_slug):
        facility = self.get_facility(request, facility_slug)
        return render(
            request,
            self.template_name,
            self.get_context(request, facility),
        )

    def post(self, request, facility_slug):
        facility = self.get_facility(request, facility_slug)
        form_data = {
            "name": request.POST.get("name", "").strip(),
            "facility_type": request.POST.get("facility_type", "").strip(),
            "description": request.POST.get("description", "").strip(),
            "status": request.POST.get("status", "").strip(),
            "capacity": request.POST.get("capacity", "").strip(),
            "notes": request.POST.get("notes", "").strip(),
        }
        errors = {}

        if not form_data["name"]:
            errors["name"] = "Enter a facility name."
        elif len(form_data["name"]) > 150:
            errors["name"] = "The name must be 150 characters or fewer."
        elif Facility.objects.filter(
            branch=request.branch,
            name__iexact=form_data["name"],
        ).exclude(pk=facility.pk).exists():
            errors["name"] = "A facility with this name already exists in this branch."

        if form_data["facility_type"] not in Facility.FacilityType.values:
            errors["facility_type"] = "Select a valid facility type."
        if form_data["status"] not in Facility.FacilityStatus.values:
            errors["status"] = "Select a valid facility status."

        capacity = None
        if not form_data["capacity"].isdecimal():
            errors["capacity"] = "Enter a capacity of zero or greater."
        else:
            capacity = int(form_data["capacity"])
            if capacity > 2147483647:
                errors["capacity"] = "Capacity must be 2,147,483,647 or fewer."

        if errors:
            return render(
                request,
                self.template_name,
                self.get_context(request, facility, form_data, errors),
            )

        facility.name = form_data["name"]
        facility.facility_type = form_data["facility_type"]
        facility.description = form_data["description"]
        facility.status = form_data["status"]
        facility.capacity = capacity
        facility.notes = form_data["notes"]
        facility.save()

        return redirect(
            "facility-detail",
            branch=request.branch.slug,
            facility_slug=facility.slug,
        )
