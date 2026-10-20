from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
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
from dashboard.models.inventory import InventoryTransaction


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
    party_size = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "class": "input input-bordered w-full",
                "min": 1,
                "step": 1,
            }
        ),
        label="Party size",
    )

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
        facility = self.instance.facility
        if facility is not None and facility.capacity > 0:
            self.fields["party_size"].widget.attrs["max"] = facility.capacity
            self.fields["party_size"].help_text = (
                f"Maximum capacity: {facility.capacity} guests."
            )
        else:
            self.fields["party_size"].help_text = (
                "Enter the number of guests for this reservation."
            )
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
            "party_size",
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

    def clean_party_size(self):
        party_size = self.cleaned_data.get("party_size")
        if party_size is None:
            return self.instance.party_size
        if (
            self.instance.facility is not None
            and not self.instance.facility.has_capacity_for(party_size)
        ):
            raise forms.ValidationError(
                "Party size cannot exceed the facility capacity "
                f"of {self.instance.facility.capacity} guests."
            )
        return party_size

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


class InventoryMovementForm(forms.Form):
    inventory = forms.ModelChoiceField(
        queryset=Inventory.objects.none(),
        label="Inventory item",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    transaction_type = forms.ChoiceField(
        choices=InventoryTransaction.Type.choices,
        initial=InventoryTransaction.Type.RECEIVED,
        label="Movement type",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    quantity = forms.IntegerField(
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "min": "0", "step": "1"}
        ),
    )
    unit_cost = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        label="Unit cost (PHP)",
        widget=forms.NumberInput(
            attrs={
                "class": "input input-bordered w-full",
                "min": "0",
                "step": "0.01",
            }
        ),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "textarea textarea-bordered w-full", "rows": 3}
        ),
    )

    def __init__(self, *args, branch, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inventory"].queryset = Inventory.objects.filter(
            branch=branch
        ).order_by("name")
        self.fields["inventory"].label_from_instance = lambda item: item.name

    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get("transaction_type")
        quantity = cleaned_data.get("quantity")

        if transaction_type in {
            InventoryTransaction.Type.ADJUSTMENT,
            InventoryTransaction.Type.RETURNED,
        }:
            if not cleaned_data.get("notes", "").strip():
                self.add_error(
                    "notes",
                    "A note is required for adjustments and returns.",
                )

        if transaction_type == InventoryTransaction.Type.ADJUSTMENT:
            if quantity is not None:
                cleaned_data["target_quantity"] = quantity
        elif transaction_type == InventoryTransaction.Type.CONSUMED:
            if quantity is not None and quantity > 0:
                cleaned_data["quantity_change"] = -quantity
        elif transaction_type in {
            InventoryTransaction.Type.RECEIVED,
            InventoryTransaction.Type.RETURNED,
        }:
            if quantity is not None and quantity > 0:
                cleaned_data["quantity_change"] = quantity
        if (
            transaction_type != InventoryTransaction.Type.ADJUSTMENT
            and quantity == 0
        ):
            self.add_error("quantity", "Enter a quantity greater than zero.")
        if transaction_type != InventoryTransaction.Type.RECEIVED:
            cleaned_data["unit_cost"] = None

        return cleaned_data


class InventoryAssetMovementForm(forms.Form):
    ASSET_EVENT_CHOICES = (
        ("", "Choose an event"),
        *(
            choice
            for choice in InventoryAssetHistory.Event.choices
            if choice[0] != InventoryAssetHistory.Event.ACQUIRED
        ),
    )

    asset = forms.ModelChoiceField(
        queryset=InventoryAsset.objects.none(),
        label="Asset",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    event_type = forms.ChoiceField(
        choices=ASSET_EVENT_CHOICES,
        label="History event",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    borrower = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        label="Borrower",
        widget=forms.HiddenInput(attrs={"data-user-picker-id": ""}),
    )
    due_date = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        required=False,
        label="Due date",
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"class": "input input-bordered w-full", "type": "datetime-local"},
        ),
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

    def __init__(self, *args, branch, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = InventoryAsset.objects.filter(
            branch=branch
        ).order_by("name")
        self.fields["borrower"].queryset = (
            get_user_model().objects.filter(is_active=True)
            .order_by("first_name", "last_name", "username")
        )
        borrower_id = self.data.get("borrower") if self.is_bound else None
        self.selected_borrower = None
        if borrower_id and str(borrower_id).isdecimal():
            self.selected_borrower = self.fields["borrower"].queryset.filter(
                pk=borrower_id
            ).first()

    @staticmethod
    def events_for_status(status):
        return {
            event_type
            for event_type in InventoryAssetStatusForm.STATUS_TRANSITIONS.get(
                status, {}
            ).values()
        }

    def clean(self):
        cleaned_data = super().clean()
        asset = cleaned_data.get("asset")
        event_type = cleaned_data.get("event_type")
        if asset is not None and event_type is not None:
            if event_type not in self.events_for_status(asset.status):
                self.add_error(
                    "event_type",
                    "This event is not available for the asset's current status.",
                )
            if event_type == InventoryAssetHistory.Event.BORROWED:
                if not cleaned_data.get("borrower"):
                    self.add_error("borrower", "Choose a borrower for this event.")
            else:
                cleaned_data["borrower"] = None
                cleaned_data["due_date"] = None
        return cleaned_data
