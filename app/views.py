from django.shortcuts import get_object_or_404, render

from dashboard.models import Branch, Facility


BRANCH_IMAGE_FALLBACK = (
    "https://images.unsplash.com/photo-1571896349842-33c89424de2d"
    "?auto=format&fit=crop&w=1800&q=85"
)
FACILITY_IMAGE_FALLBACKS = {
    Facility.FacilityType.POOL: (
        "https://images.unsplash.com/photo-1576013551627-0cc20b96c2a7"
        "?auto=format&fit=crop&w=1200&q=80"
    ),
    Facility.FacilityType.GYM: (
        "https://images.unsplash.com/photo-1534438327276-14e5300c3a48"
        "?auto=format&fit=crop&w=1200&q=80"
    ),
    Facility.FacilityType.RESTAURANT: (
        "https://images.unsplash.com/photo-1414235077428-338989a2e8c0"
        "?auto=format&fit=crop&w=1200&q=80"
    ),
    Facility.FacilityType.EVENT_HALL: (
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3"
        "?auto=format&fit=crop&w=1200&q=80"
    ),
}


def _add_facility_images(facilities):
    for facility in facilities:
        facility.public_image_url = facility.image_url or FACILITY_IMAGE_FALLBACKS.get(
            facility.facility_type,
            BRANCH_IMAGE_FALLBACK,
        )
    return facilities

def home(request):
    branches = Branch.objects.order_by("name")
    facilities = Facility.objects.filter(
        status=Facility.FacilityStatus.OPERATIONAL
    ).select_related("branch").order_by("branch__name", "name")
    return render(
        request,
        "root.html",
        {
            "branches": branches,
            "facilities": _add_facility_images(facilities),
            "branch_image_fallback": BRANCH_IMAGE_FALLBACK,
        },
    )


def branch_list(request):
    return render(
        request,
        "public/branches.html",
        {
            "branches": Branch.objects.order_by("name"),
            "branch_image_fallback": BRANCH_IMAGE_FALLBACK,
        },
    )


def branch_detail(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    facilities = _add_facility_images(
        branch.facilities.order_by("name")
    )
    return render(
        request,
        "public/branch_detail.html",
        {
            "branch": branch,
            "facilities": facilities,
            "branch_image_fallback": BRANCH_IMAGE_FALLBACK,
        },
    )


def facility_list(request):
    facilities = Facility.objects.select_related("branch").order_by(
        "branch__name", "name"
    )
    return render(
        request,
        "public/facilities.html",
        {"facilities": _add_facility_images(facilities)},
    )


def facility_detail(request, slug):
    facility = get_object_or_404(
        Facility.objects.select_related("branch"),
        slug=slug,
    )
    other_facilities = Facility.objects.filter(
        branch=facility.branch
    ).exclude(pk=facility.pk).order_by("name")
    return render(
        request,
        "public/facility_detail.html",
        {
            "facility": _add_facility_images([facility])[0],
            "other_facilities": _add_facility_images(other_facilities),
        },
    )