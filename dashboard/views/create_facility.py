from decimal import Decimal, InvalidOperation

from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models.branches_facilities import Facility


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class CreateFacilityView(View):
    template_name = "facilities-maintenance/create_facility.html"

    def get_context(self, request, form_data=None, errors=None):
        return {
            "branch": request.branch,
            "facility_types": Facility.FacilityType.choices,
            "facility_statuses": Facility.FacilityStatus.choices,
            "form_data": form_data or {
                "name": "",
                "facility_type": Facility.FacilityType.POOL,
                "image_url": "",
                "description": "",
                "status": Facility.FacilityStatus.OPERATIONAL,
                "capacity": "0",
                "rate_24hours": "",
                "rate_22hours": "",
                "rate_morning": "",
                "rate_evening": "",
                "rate_per_extra_hour": "",
            },
            "errors": errors or {},
            "hide_aside": True,
        }

    def get(self, request):
        return render(
            request,
            self.template_name,
            self.get_context(request),
        )

    def parse_optional_rate(self, form_data, field_name, errors, label):
        value = form_data[field_name].strip()
        if not value:
            return None
        try:
            parsed = Decimal(value)
            if (
                not parsed.is_finite()
                or parsed <= Decimal("1.00")
                or parsed > Decimal("2147483647.99")
                or parsed.as_tuple().exponent < -2
            ):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errors[field_name] = f"Enter {label} greater than 1.00 with up to 2 decimal places."
            return None
        return parsed.quantize(Decimal("0.01"))

    def post(self, request):
        form_data = {
            "name": request.POST.get("name", "").strip(),
            "facility_type": request.POST.get("facility_type", "").strip(),
            "image_url": request.POST.get("image_url", "").strip(),
            "description": request.POST.get("description", "").strip(),
            "status": request.POST.get("status", "").strip(),
            "capacity": request.POST.get("capacity", "").strip(),
            "rate_24hours": request.POST.get("rate_24hours", "").strip(),
            "rate_22hours": request.POST.get("rate_22hours", "").strip(),
            "rate_morning": request.POST.get("rate_morning", "").strip(),
            "rate_evening": request.POST.get("rate_evening", "").strip(),
            "rate_per_extra_hour": request.POST.get(
                "rate_per_extra_hour", ""
            ).strip(),
        }
        errors = {}

        if not form_data["name"]:
            errors["name"] = "Enter a facility name."
        elif len(form_data["name"]) > 150:
            errors["name"] = "The name must be 150 characters or fewer."
        elif Facility.objects.filter(
            branch=request.branch,
            name__iexact=form_data["name"],
        ).exists():
            errors["name"] = "A facility with this name already exists in this branch."

        if form_data["facility_type"] not in Facility.FacilityType.values:
            errors["facility_type"] = "Select a valid facility type."
        if form_data["status"] not in Facility.FacilityStatus.values:
            errors["status"] = "Select a valid facility status."
        if len(form_data["image_url"]) > 255:
            errors["image_url"] = "The image URL must be 255 characters or fewer."

        capacity = None
        if not form_data["capacity"].isdecimal():
            errors["capacity"] = "Enter a capacity of zero or greater."
        else:
            capacity = int(form_data["capacity"])
            if capacity > 2147483647:
                errors["capacity"] = "Capacity must be 2,147,483,647 or fewer."

        rates = {
            field: self.parse_optional_rate(
                form_data,
                field,
                errors,
                label,
            )
            for field, label in (
                ("rate_24hours", "The 24-hour rate"),
                ("rate_22hours", "The 22-hour rate"),
                ("rate_morning", "The morning rate"),
                ("rate_evening", "The evening rate"),
                ("rate_per_extra_hour", "The extra-hour rate"),
            )
        }

        if errors:
            return render(
                request,
                self.template_name,
                self.get_context(request, form_data, errors),
            )

        base_slug = slugify(form_data["name"]) or "facility"
        slug = base_slug
        suffix = 2
        while Facility.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        facility = Facility.objects.create(
            branch=request.branch,
            name=form_data["name"],
            slug=slug,
            facility_type=form_data["facility_type"],
            image_url=form_data["image_url"] or None,
            description=form_data["description"],
            status=form_data["status"],
            capacity=capacity,
            **rates,
        )

        return redirect(
            "facility-detail",
            branch=request.branch.slug,
            facility_slug=facility.slug,
        )
