from django.test import TestCase
from django.urls import reverse

from dashboard.models import Branch, Facility


class PublicResortPagesTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Coastal Branch",
            slug="coastal-branch",
            city="Seabrook",
            address="1 Shore Road",
            description="A quiet coastal retreat.",
        )
        self.operational_facility = Facility.objects.create(
            branch=self.branch,
            name="Garden Pool",
            slug="garden-pool",
            status=Facility.FacilityStatus.OPERATIONAL,
            description="A quiet place to swim.",
        )
        self.closed_facility = Facility.objects.create(
            branch=self.branch,
            name="Event Pavilion",
            slug="event-pavilion",
            facility_type=Facility.FacilityType.EVENT_HALL,
            status=Facility.FacilityStatus.CLOSED,
            description="Currently closed for seasonal work.",
        )

    def test_all_public_pages_are_accessible_without_authentication(self):
        urls = (
            reverse("home"),
            reverse("branch-list"),
            reverse("branch-detail", kwargs={"slug": self.branch.slug}),
            reverse("facility-list"),
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.operational_facility.slug},
            ),
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.closed_facility.slug},
            ),
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_homepage_only_lists_operational_facilities(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, self.operational_facility.name)
        self.assertNotContains(response, self.closed_facility.name)

    def test_other_public_pages_show_non_operational_facilities(self):
        branch_response = self.client.get(
            reverse("branch-detail", kwargs={"slug": self.branch.slug})
        )
        facility_list_response = self.client.get(reverse("facility-list"))
        facility_response = self.client.get(
            reverse(
                "public-facility-detail",
                kwargs={"slug": self.closed_facility.slug},
            )
        )

        self.assertContains(branch_response, self.closed_facility.name)
        self.assertContains(branch_response, "Closed")
        self.assertContains(facility_list_response, self.closed_facility.name)
        self.assertContains(facility_response, self.branch.name)
        self.assertContains(
            facility_response,
            "Currently closed for seasonal work.",
        )

    def test_inquiry_is_a_nonfunctional_placeholder(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, 'type="button" disabled aria-disabled="true"')
        self.assertContains(response, "Make an inquiry")