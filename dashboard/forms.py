from decimal import Decimal

from django import forms
from django.db.models import Sum
from django.utils import timezone

from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.models import Payment, Reservation


class PaymentForm(forms.ModelForm):
    def __init__(self, *args, reservation, **kwargs):
        self.reservation = reservation
        super().__init__(*args, **kwargs)

    class Meta:
        model = Payment
        fields = ("amount", "type", "method", "transaction_reference")
        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": "0.01",
                    "step": "0.01",
                }
            ),
            "type": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "method": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
            "transaction_reference": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
        }
        labels = {
            "method": "Payment method",
            "transaction_reference": "Transaction reference (optional)",
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Enter an amount greater than zero.")

        paid_total = (
            self.reservation.payments.filter(
                status=Payment.Status.SUCCEEDED,
                currency="PHP",
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        remaining = max(
            self.reservation.total_amount - paid_total,
            Decimal("0.00"),
        )
        if amount > remaining:
            raise forms.ValidationError(
                f"Amount cannot exceed the remaining balance of PHP {remaining:.2f}."
            )
        return amount


class ReservationEditForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "input input-bordered w-full",
                "type": "datetime-local",
            },
        ),
    )
    ends_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "input input-bordered w-full",
                "type": "datetime-local",
            },
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial["starts_at"] = timezone.localtime(
                self.instance.starts_at
            ).strftime("%Y-%m-%dT%H:%M")
            self.initial["ends_at"] = timezone.localtime(
                self.instance.ends_at
            ).strftime("%Y-%m-%dT%H:%M")

    class Meta:
        model = Reservation
        fields = (
            "starts_at",
            "ends_at",
            "special_requests",
            "discount",
            "status",
        )
        widgets = {
            "special_requests": forms.Textarea(
                attrs={
                    "class": "textarea textarea-bordered w-full",
                    "rows": 4,
                }
            ),
            "discount": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": "0",
                    "step": "0.01",
                }
            ),
            "status": forms.Select(
                attrs={"class": "select select-bordered w-full"}
            ),
        }

    def clean_discount(self):
        discount = self.cleaned_data["discount"]
        if discount < 0:
            raise forms.ValidationError("Discount cannot be negative.")
        return discount

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")
        discount = cleaned_data.get("discount")

        if starts_at is None or ends_at is None:
            return cleaned_data
        if ends_at <= starts_at:
            self.add_error("ends_at", "End time must be after start time.")
            return cleaned_data

        schedule_changed = (
            starts_at != self.instance.starts_at
            or ends_at != self.instance.ends_at
        )
        if schedule_changed and self.instance.facility is None:
            self.add_error(
                "ends_at",
                "A facility is required to check availability and rates.",
            )
            return cleaned_data

        raw_amount = self.instance.raw_amount
        if schedule_changed:
            raw_amount = calculate_total_amount(
                self.instance.facility,
                starts_at,
                ends_at,
            )
            if raw_amount is None:
                self.add_error("ends_at", RATE_REQUIRED_ERROR)
                return cleaned_data
        self.calculated_raw_amount = raw_amount

        if (
            discount is not None
            and raw_amount is not None
            and discount > raw_amount
        ):
            self.add_error(
                "discount",
                "Discount cannot be greater than the reservation amount.",
            )
        return cleaned_data
