import uuid
from datetime import time, timedelta, timezone as datetime_timezone
from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from app.fields import TitleCaseCharField


class ReservationManager(models.Manager):
    def has_guest_time_conflict(self, guest, starts_at, ends_at):
        return self.filter(
            guest=guest,
            status__in=(
                Reservation.Status.PENDING,
                Reservation.Status.CONFIRMED,
            ),
            starts_at__lt=ends_at,
            ends_at__gt=starts_at,
        ).exists()

    def cancel_pending_payments(self, reservation):
        return reservation.payments.filter(
            status=Payment.Status.PENDING,
        ).update(
            status=Payment.Status.CANCELLED,
            updated_at=timezone.now(),
        )

    def decline_conflicts(self, reservation):
        return self.filter(
            facility_id=reservation.facility_id,
            status=Reservation.Status.PENDING,
            starts_at__lt=reservation.ends_at,
            ends_at__gt=reservation.starts_at,
        ).exclude(pk=reservation.pk).update(
            status=Reservation.Status.DECLINED,
            updated_at=timezone.now(),
        )

    def calculate_raw_amount(
        self,
        facility,
        starts_at,
        ends_at,
        rate_package=None,
    ):
        duration = ends_at.astimezone(datetime_timezone.utc) - starts_at.astimezone(
            datetime_timezone.utc
        )
        day_length = timedelta(hours=24)

        if rate_package is None:
            rate = None
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

        package_durations = {
            Reservation.RatePackage.TWENTY_FOUR_HOURS: day_length,
            Reservation.RatePackage.TWENTY_TWO_HOURS: timedelta(hours=22),
            Reservation.RatePackage.MORNING: timedelta(hours=9),
            Reservation.RatePackage.EVENING: timedelta(hours=11),
        }
        package_rates = {
            Reservation.RatePackage.TWENTY_FOUR_HOURS: facility.rate_24hours,
            Reservation.RatePackage.TWENTY_TWO_HOURS: facility.rate_22hours,
            Reservation.RatePackage.MORNING: facility.rate_morning,
            Reservation.RatePackage.EVENING: facility.rate_evening,
        }
        package_duration = package_durations.get(rate_package)
        rate = package_rates.get(rate_package)
        if package_duration is None or rate is None or duration < package_duration:
            return None

        if rate_package == Reservation.RatePackage.MORNING:
            if timezone.localtime(starts_at).time() != time(8):
                return None
        elif rate_package == Reservation.RatePackage.EVENING:
            if timezone.localtime(starts_at).time() != time(19):
                return None

        if rate_package == Reservation.RatePackage.TWENTY_FOUR_HOURS:
            package_count = duration // day_length
            extra_duration = duration % day_length
        else:
            package_count = 1
            extra_duration = duration - package_duration

        extra_hour = timedelta(hours=1)
        if extra_duration % extra_hour != timedelta(0):
            return None

        amount = Decimal(rate) * package_count
        if extra_duration:
            extra_rate = facility.rate_per_extra_hour
            if extra_rate is None:
                return None
            amount += Decimal(extra_rate) * (extra_duration // extra_hour)
        return amount

    def calculate_extra_hour_amount(
        self,
        facility,
        starts_at,
        ends_at,
        rate_package,
    ):
        if rate_package is None:
            return Decimal("0.00")

        duration = ends_at.astimezone(datetime_timezone.utc) - starts_at.astimezone(
            datetime_timezone.utc
        )
        package_durations = {
            Reservation.RatePackage.TWENTY_FOUR_HOURS: timedelta(hours=24),
            Reservation.RatePackage.TWENTY_TWO_HOURS: timedelta(hours=22),
            Reservation.RatePackage.MORNING: timedelta(hours=9),
            Reservation.RatePackage.EVENING: timedelta(hours=11),
        }
        package_duration = package_durations.get(rate_package)
        if package_duration is None or duration < package_duration:
            return Decimal("0.00")

        if rate_package == Reservation.RatePackage.TWENTY_FOUR_HOURS:
            extra_duration = duration % package_duration
        else:
            extra_duration = duration - package_duration
        extra_hour = timedelta(hours=1)
        if extra_duration % extra_hour != timedelta(0):
            return None
        if not extra_duration:
            return Decimal("0.00")
        if facility.rate_per_extra_hour is None:
            return None
        return Decimal(facility.rate_per_extra_hour) * (
            extra_duration // extra_hour
        )

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
                reservation.rate_package,
            )
            reservation.extra_hour_amount = (
                self.calculate_extra_hour_amount(
                    reservation.facility,
                    reservation.starts_at,
                    reservation.ends_at,
                    reservation.rate_package,
                )
                or Decimal("0.00")
            )
            reservation.extra_hour_rate = reservation.facility.rate_per_extra_hour
        self._for_write = True
        reservation.save(force_insert=True, using=self.db)
        return reservation


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        DECLINED = "declined", "Declined"

    class RatePackage(models.TextChoices):
        TWENTY_FOUR_HOURS = "24hours", "24-hour rate"
        TWENTY_TWO_HOURS = "22hours", "22-hour rate"
        MORNING = "morning", "Morning rate"
        EVENING = "evening", "Evening rate"

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
    rate_package = models.CharField(
        max_length=20,
        choices=RatePackage.choices,
        null=True,
        blank=True,
    )
    extra_hour_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    extra_hour_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
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

    @property
    def base_amount(self):
        if self.raw_amount is None:
            return None
        return self.raw_amount - self.extra_hour_amount

    @property
    def current_status(self):
        calendar_entry = getattr(self, "calendar_entry", None)
        if self.status == Reservation.Status.CONFIRMED and calendar_entry:
            return calendar_entry.status
        return self.status

    @property
    def current_status_display(self):
        calendar_entry = getattr(self, "calendar_entry", None)
        if self.status == Reservation.Status.CONFIRMED and calendar_entry:
            return calendar_entry.get_status_display()
        return self.get_status_display()


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
    notes = models.TextField(blank=True)
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
        else:
            if self.booking_reference is None:
                self.booking_reference = uuid.uuid4()
            Reservation.objects.filter(pk=self.reservation_id).update(
                status=Reservation.Status.CONFIRMED,
                updated_at=timezone.now(),
            )
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
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    reservation_id = models.ForeignKey(
        "Reservation",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    name = TitleCaseCharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=50)
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
    cashier = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        related_name="cashier_payments",
        blank=True,
        null=True,
    )
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} for {self.reservation_id}"
