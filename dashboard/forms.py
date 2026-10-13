from decimal import Decimal

from django import forms
from django.db.models import Sum
from django.utils import timezone

from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.models import (
    Inventory,
    InventoryAsset,
    InventoryAssetHistory,
    Payment,
    Reservation,
)


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


class InventoryItemCreateForm(forms.ModelForm):
    opening_quantity = forms.IntegerField(
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(
            attrs={
                "class": "input input-bordered w-full",
                "min": "0",
                "step": "1",
            }
        ),
        help_text="If entered, this will be recorded as opening stock.",
    )

    class Meta:
        model = Inventory
        fields = ("name", "sku", "unit", "reorder_level", "unit_cost", "notes")
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "sku": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "unit": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "reorder_level": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": "0",
                    "step": "1",
                }
            ),
            "unit_cost": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": "0",
                    "step": "0.01",
                    "placeholder": "0.00",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "textarea textarea-bordered w-full",
                    "rows": 3,
                }
            ),
        }
        labels = {"unit_cost": "Unit cost (PHP)"}

    def clean_unit_cost(self):
        unit_cost = self.cleaned_data.get("unit_cost")
        if unit_cost is not None and unit_cost < 0:
            raise forms.ValidationError("Unit cost cannot be negative.")
        return unit_cost


class InventoryAssetCreateForm(forms.ModelForm):
    class Meta:
        model = InventoryAsset
        fields = (
            "name",
            "asset_tag",
            "category",
            "brand",
            "serial_number",
            "purchase_date",
            "purchase_cost",
            "notes",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "asset_tag": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
            "category": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "list": "resort-asset-categories",
                    "placeholder": "Choose or enter a category",
                }
            ),
            "brand": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "placeholder": "e.g. Samsung",
                }
            ),
            "serial_number": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
            "purchase_date": forms.DateInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "type": "date",
                }
            ),
            "purchase_cost": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": "0",
                    "step": "0.01",
                    "placeholder": "0.00",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "textarea textarea-bordered w-full",
                    "rows": 3,
                }
            ),
        }
        labels = {"purchase_cost": "Purchase cost (PHP)"}

    def clean_purchase_cost(self):
        purchase_cost = self.cleaned_data.get("purchase_cost")
        if purchase_cost is not None and purchase_cost < 0:
            raise forms.ValidationError("Purchase cost cannot be negative.")
        return purchase_cost


class InventoryAssetStatusForm(forms.Form):
    STATUS_TRANSITIONS = {
        InventoryAsset.Status.ACTIVE: {
            InventoryAsset.Status.BORROWED: InventoryAssetHistory.Event.BORROWED,
            InventoryAsset.Status.IN_MAINTENANCE: (
                InventoryAssetHistory.Event.MAINTENANCE_STARTED
            ),
            InventoryAsset.Status.RETIRED: InventoryAssetHistory.Event.RETIRED,
            InventoryAsset.Status.DISPOSED: InventoryAssetHistory.Event.DISPOSED,
        },
        InventoryAsset.Status.BORROWED: {
            InventoryAsset.Status.ACTIVE: InventoryAssetHistory.Event.RETURNED,
        },
        InventoryAsset.Status.IN_MAINTENANCE: {
            InventoryAsset.Status.ACTIVE: (
                InventoryAssetHistory.Event.MAINTENANCE_COMPLETED
            ),
            InventoryAsset.Status.RETIRED: InventoryAssetHistory.Event.RETIRED,
            InventoryAsset.Status.DISPOSED: InventoryAssetHistory.Event.DISPOSED,
        },
        InventoryAsset.Status.RETIRED: {
            InventoryAsset.Status.DISPOSED: InventoryAssetHistory.Event.DISPOSED,
        },
        InventoryAsset.Status.DISPOSED: {},
    }

    status = forms.ChoiceField(
        label="New status",
        choices=(),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    notes = forms.CharField(
        label="History note",
        widget=forms.Textarea(
            attrs={
                "class": "textarea textarea-bordered w-full",
                "rows": 3,
                "required": True,
            }
        ),
    )

    def __init__(self, *args, asset, **kwargs):
        self.asset = asset
        super().__init__(*args, **kwargs)
        transitions = self.STATUS_TRANSITIONS[asset.status]
        self.fields["status"].choices = [
            ("", asset.get_status_display())
        ] + [
            (status, InventoryAsset.Status(status).label)
            for status in transitions
            if status != InventoryAsset.Status.BORROWED
        ]
        if not transitions:
            self.fields.clear()

    @property
    def event_type(self):
        return self.STATUS_TRANSITIONS[self.asset.status][
            self.cleaned_data["status"]
        ]
