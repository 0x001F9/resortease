from django.urls import reverse

from langchain.tools import tool

from dashboard.models import Branch, Facility


@tool
def get_branch(branch: str | None = None) -> list[dict]:
    """Fetch branch details, or all branches when branch is None.

    Args:
        branch: Exact branch name, or None to fetch every branch.
    """
    if branch is not None:
        branches = branches.filter(name__iexact=branch.strip())
    else:
        branches = Branch.objects.order_by("name")

    return [
        {
            "name": row.name,
            "page_url": reverse("branch-detail", kwargs={"slug": row.slug}),
            "description": row.description,
            "address": row.address,
            "phone_number": row.phone_number,
            "email": row.email or "",
            "city": row.city,
            "facilities": list(
                row.facilities.order_by("name").values_list("name", flat=True)
            ),
        }
        for row in branches
    ]


@tool
def get_facility(
    branch: str,
    facility: str | None = None,
) -> list[dict]:
    """Fetch one facility or all facilities belonging to a branch.

    Args:
        branch: Exact name of the branch that owns the facilities.
        facility: Exact facility name, or None to fetch all facilities in the branch.
    """
    branches = Branch.objects.filter(name__iexact=branch.strip())
    branch_row = branches.first()
    if branch_row is None:
        return []

    facilities = Facility.objects.filter(branch=branch_row).order_by("name")
    if facility is not None:
        facilities = facilities.filter(name__iexact=facility.strip())

    return [
        {
            "name": row.name,
            "page_url": reverse(
                "public-facility-detail",
                kwargs={"slug": row.slug},
            ),
            "facility_type": row.get_facility_type_display(),
            "description": row.description,
            "status": row.get_status_display(),
            "capacity": row.capacity,
            "rates": {
                "24hours": row.rate_24hours if row.rate_24hours is not None and row.rate_24hours > 0 else "Unavailable",
                "22hours": row.rate_22hours if row.rate_22hours is not None and row.rate_22hours > 0 else "Unavailable",
                "morning": row.rate_morning if row.rate_morning is not None and row.rate_morning > 0 else "Unavailable",
                "evening": row.rate_evening if row.rate_evening is not None and row.rate_evening > 0 else "Unavailable",
                "per_extra_hour": row.rate_per_extra_hour if row.rate_per_extra_hour is not None and row.rate_per_extra_hour > 0 else "Unavailable",
            },
        }
        for row in facilities
    ]
