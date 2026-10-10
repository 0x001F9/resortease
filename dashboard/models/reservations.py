import uuid
from datetime import time, timedelta, timezone as datetime_timezone
from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class ReservationManager(models.Manager):
    def calculate_raw_amount(self, facility, starts_at, ends_at):
        duration = ends_at.astimezone(datetime_timezone.utc) - starts_at.astimezone(
            datetime_timezone.utc
        )
        rate = None

        day_length = timedelta(hours=24)
        if duration >= day_length and duration % day_length == timedelta(0):
            rate = facility.rate_24hours
            if rate is not None:
                rate *= duration // day_length
        elif duration == timedelta(hours=22):
            rate = facility.rate_22hours
        else:
            local_start = timezone.localtime(starts_at)
            local_end = timezone.localtime(ends_at)
            if (
                local_start.time() == time(8)
                and local_end.time() == time(17)
                and local_start.date() == local_end.date()
            ):
                rate = facility.rate_morning
            elif (
                local_start.time() == time(19)
                and local_end.time() == time(6)
                and local_end.date() == local_start.date() + timedelta(days=1)
            ):
                rate = facility.rate_evening

        return Decimal(rate) if rate is not None else None

    def create(self, **kwargs):
        reservation = self.model(**kwargs)
        if (
            reservation.facility_id is not None
            and reservation.starts_at is not None
            and reservation.ends_at is not None
        ):
            reservation.raw_amount = self.calculate_raw_amount(
                reservation.facility,
                reservation.starts_at,
                reservation.ends_at,
            )
        self._for_write = True
        reservation.save(force_insert=True, using=self.db)
        return reservation


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

    raw_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
    )

    objects = ReservationManager()

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

    @property
    def total_amount(self):
        if self.raw_amount is None:
            return None
        return max(self.raw_amount - self.discount, Decimal("0.00"))


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
            self.status = self.Status.UNAVAILABLE
        elif self.booking_reference is None:
            self.booking_reference = uuid.uuid4()
        super().save(*args, **kwargs)

    @property
    def is_unavailable(self):
        return self.reservation_id is None

    @property
    def has_amount(self):
        return (
            self.reservation_id is not None
            and self.reservation.raw_amount is not None
        )


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
