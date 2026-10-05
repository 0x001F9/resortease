from django.db import models
from account.models import User

class Branch(models.Model):
    name = models.CharField(max_length=150, unique=True)
    slug = models.CharField(max_length=255, unique=True)
    city = models.CharField(max_length=100)
    address = models.TextField()
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True, null=True)
    manager_id = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_branches",
        limit_choices_to={
            "role__in": [
                User.Role.OperationManager,
                User.Role.GeneralManager,
            ]
        }
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "branches"

    def __str__(self):
        return self.name


class Facility(models.Model):
    class FacilityStatus(models.TextChoices):
        OPERATIONAL = "operational", "Operational"
        MAINTENANCE = "maintenance", "Under maintenance"
        CLOSED = "closed", "Closed"
    
    class FacilityType(models.TextChoices):
        POOL = "pool", "Swimming Pool"
        GYM = "gym", "Gym"
        RESTAURANT = "restaurant", "Restaurant"
        EVENT_HALL = "event_hall", "Event Hall"

    branch = models.ForeignKey("Branch", related_name="facilities", on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    slug = models.CharField(max_length=255, unique=True)
    facility_type = models.CharField(
        max_length=100,
        choices=FacilityType,
        default=FacilityType.POOL
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=30,
        choices=FacilityStatus.choices,
        default=FacilityStatus.OPERATIONAL,
    )
    capacity = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "facilities"
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="unique_branch_facility_name")
        ]

    def __str__(self):
        return f"{self.branch.name} - {self.name}"


class Maintenance(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    facility = models.ForeignKey(
        "Facility", 
        related_name="maintenance_requests", 
        on_delete=models.CASCADE
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    issue_type = models.CharField(max_length=80)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    reported_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True
    )
    
    scheduled_for = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "maintenance"
        ordering = ["-reported_at"]

    def __str__(self):
        return f"{self.facility.name}: {self.title}"
