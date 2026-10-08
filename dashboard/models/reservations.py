import uuid

from django.db import models
from django.db.models import F, Q


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    guest = models.ForeignKey(
        "account.User",
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    facility = models.ForeignKey(
        "Facility",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservations",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    party_size = models.PositiveIntegerField(default=1)
    special_requests = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reservations"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="reservation_ends_after_starts",
            )
        ]

    def __str__(self):
        return f"Reservation {self.pk} - {self.guest}"


class Calendar(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
        UNAVAILABLE = "unavailable", "Unavailable"

    reservation = models.OneToOneField(
        "Reservation",
        on_delete=models.PROTECT,
        related_name="calendar_entry",
        null=True,
        blank=True,
    )
    facility = models.ForeignKey(
        "Facility",
        on_delete=models.PROTECT,
        related_name="calendar_entries",
    )
    booking_reference = models.UUIDField(
        default=None,
        unique=True,
        editable=False,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "calendar"
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="calendar_ends_after_starts",
            )
        ]

    def __str__(self):
        if self.reservation_id is None:
            return f"Unavailable: {self.facility} ({self.starts_at})"
        return f"Booking {self.booking_reference}"

    def save(self, *args, **kwargs):
        if self.reservation_id is None:
            self.booking_reference = None
            self.total_amount = None
            self.status = self.Status.UNAVAILABLE
        elif self.booking_reference is None:
            self.booking_reference = uuid.uuid4()
        super().save(*args, **kwargs)

    @property
    def is_unavailable(self):
        return self.reservation_id is None

    @property
    def has_amount(self):
        return self.total_amount is not None


class Payment(models.Model):
    class Method(models.TextChoices):
        CARD = "card", "Card"
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    calendar_entry = models.ForeignKey(
        "Calendar",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    transaction_reference = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
    )
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.pk} for {self.calendar_entry}"
