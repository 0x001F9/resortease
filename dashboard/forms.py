from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from app.fields import TitleCaseFormField
from dashboard.billing import RATE_REQUIRED_ERROR, calculate_total_amount
from dashboard.models import (
    Calendar,
    Inventory,
    InventoryAsset,
    InventoryAssetHistory,
    Payment,
    Reservation,
)
from dashboard.models.inventory import InventoryTransaction


class PaymentForm(forms.ModelForm):
    name = TitleCaseFormField(
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "input input-bordered w-full",
                "list": "payment-name-options",
            }
        ),
    )
    status = forms.ChoiceField(
        choices=(
            (Payment.Status.PENDING, Payment.Status.PENDING.label),
            (Payment.Status.SUCCEEDED, Payment.Status.SUCCEEDED.label),
        ),
        initial=Payment.Status.PENDING,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(
        self,
        *args,
        pending_only=False,
        refund_only=False,
        refund_amount=None,
        refund_limit=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.refund_amount = refund_amount
        self.refund_limit = refund_limit
        if refund_only:
            self.fields["status"].choices = (
                (Payment.Status.REFUNDED, Payment.Status.REFUNDED.label),
            )
            self.initial["status"] = Payment.Status.REFUNDED
            self.initial["name"] = "Refund"
            self.initial["amount"] = refund_amount
            self.fields["amount"].widget.attrs["readonly"] = True
        elif pending_only:
            self.fields["status"].choices = (
                (Payment.Status.PENDING, Payment.Status.PENDING.label),
            )
            self.initial["status"] = Payment.Status.PENDING
        elif refund_limit is not None and refund_limit > 0:
            self.fields["status"].choices = (
                *self.fields["status"].choices,
                (Payment.Status.REFUNDED, Payment.Status.REFUNDED.label),
            )
            self.fields["amount"].widget.attrs["max"] = f"{refund_limit:.2f}"
            self.fields["amount"].help_text = (
                f"Refunds cannot exceed the remaining amount paid: "
                f"₱ {refund_limit:.2f}."
            )
        selected_status = (
            self.data.get(self.add_prefix("status"))
            if self.is_bound
            else self.initial.get("status", Payment.Status.PENDING)
        )
        self.fields["method"].required = selected_status in {
            Payment.Status.SUCCEEDED,
            Payment.Status.REFUNDED,
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("status") not in {
            Payment.Status.SUCCEEDED,
            Payment.Status.REFUNDED,
        }:
            cleaned_data["method"] = ""
            cleaned_data["transaction_reference"] = None
        if (
            cleaned_data.get("status") == Payment.Status.REFUNDED
            and self.refund_limit is not None
            and cleaned_data.get("amount") is not None
            and cleaned_data["amount"] > self.refund_limit
        ):
            self.add_error(
                "amount",
                "The refund cannot exceed the remaining amount already paid.",
            )
        return cleaned_data

    class Meta:
        model = Payment
        fields = ("name", "amount", "status", "method", "transaction_reference")
        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": "0.01",
                    "step": "0.01",
                }
            ),
            "method": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
            "transaction_reference": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
        }
        labels = {
            "name": "Payment name",
            "amount": "Amount (₱)",
            "method": "Payment method",
            "transaction_reference": "Transaction reference (optional)",
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Enter an amount greater than zero.")
        if self.refund_amount is not None and amount != self.refund_amount:
            raise forms.ValidationError(
                "The refund amount must be exactly 50% of the total paid."
            )
        return amount


class ReservationEditForm(forms.ModelForm):
    status = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "select select-bordered w-full"})
    )
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
        is_past_confirmed = (
            self.instance.pk
            and self.instance.status == Reservation.Status.CONFIRMED
            and self.instance.ends_at < timezone.now()
        )
        if is_past_confirmed:
            self.fields["starts_at"].disabled = True
            self.fields["starts_at"].help_text = (
                "The start time cannot be changed after the booking has ended."
            )
        if (
            self.instance.pk
            and (
                self.instance.status == Reservation.Status.PENDING
                or (
                    self.instance.status == Reservation.Status.CONFIRMED
                    and self.instance.ends_at >= timezone.now()
                )
            )
        ):
            if self.instance.status == Reservation.Status.PENDING:
                self.fields["status"].choices = [
                    choice
                    for choice in Reservation.Status.choices
                    if choice[0] != Reservation.Status.CONFIRMED
                ]
            else:
                excluded_statuses = {
                    Calendar.Status.UNAVAILABLE,
                    Calendar.Status.CONFIRMED,
                    Calendar.Status.COMPLETED,
                }
                self.fields["status"].choices = [
                    choice
                    for choice in Calendar.Status.choices
                    if choice[0] not in excluded_statuses
                ]
        elif self.instance.pk and self.instance.status == Reservation.Status.CONFIRMED:
            self.fields["status"].choices = [
                choice
                for choice in Calendar.Status.choices
                if choice[0] != Calendar.Status.UNAVAILABLE
            ]
        elif self.instance.pk:
            self.fields["status"].choices = Reservation.Status.choices
            if self.instance.status == Reservation.Status.DECLINED:
                self.fields["status"].choices = [
                    choice
                    for choice in Reservation.Status.choices
                    if choice[0] != Reservation.Status.CONFIRMED
                ]

        if self.instance.pk:
            current_status = self.instance.current_status

            choices = list(self.fields["status"].choices)
            choice_values = {value for value, _label in choices}
            if (
                current_status != Calendar.Status.UNAVAILABLE
                and current_status not in choice_values
            ):
                current_label = dict(Calendar.Status.choices).get(
                    current_status
                )
                if current_label is None:
                    current_label = dict(Reservation.Status.choices).get(
                        current_status
                    )
                if current_label is not None:
                    choices.append((current_status, current_label))

            self.fields["status"].choices = [
                (
                    value,
                    (
                        f"{label} (Current)"
                        if value == current_status
                        else label
                    ),
                )
                for value, label in choices
            ]

        if self.instance.pk and not self.is_bound:
            current_status = self.instance.current_status
            choice_values = {
                value for value, _label in self.fields["status"].choices
            }
            if (
                current_status != Calendar.Status.UNAVAILABLE
                and current_status in choice_values
            ):
                self.initial["status"] = current_status
        if facility is not None and facility.capacity > 0:
            self.fields["party_size"].help_text = (
                f"Facility capacity: {facility.capacity} guests. "
                "Staff may record larger parties."
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

    def _get_validation_exclusions(self):
        exclude = super()._get_validation_exclusions()
        if self.instance.status == Reservation.Status.CONFIRMED:
            exclude.add("status")
        return exclude

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
        return party_size

    def clean_status(self):
        status = self.cleaned_data["status"]
        if self.instance.status == Reservation.Status.PENDING:
            if status == Reservation.Status.CONFIRMED:
                raise forms.ValidationError(
                    "Confirmed is not available for this reservation."
                )
        elif self.instance.status == Reservation.Status.CONFIRMED:
            valid_statuses = {
                value
                for value, _label in Calendar.Status.choices
                if value != Calendar.Status.UNAVAILABLE
            }
            ends_at = self.cleaned_data.get("ends_at", self.instance.ends_at)
            calendar_entry = getattr(self.instance, "calendar_entry", None)
            if ends_at >= timezone.now():
                valid_statuses.discard(Calendar.Status.CONFIRMED)
                valid_statuses.discard(Calendar.Status.COMPLETED)
                if (
                    calendar_entry is not None
                    and calendar_entry.status in {
                        Calendar.Status.CONFIRMED,
                        Calendar.Status.COMPLETED,
                    }
                ):
                    valid_statuses.add(calendar_entry.status)
            if status not in valid_statuses:
                raise forms.ValidationError(
                    "Select a valid status for this booking."
                )
        elif status == Reservation.Status.CONFIRMED:
            raise forms.ValidationError(
                "Confirmed is not available for this reservation."
            )
        return status

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")
        discount = cleaned_data.get("discount")

        if starts_at is None or ends_at is None:
            return cleaned_data
        is_past_confirmed = (
            self.instance.pk
            and self.instance.status == Reservation.Status.CONFIRMED
            and self.instance.ends_at < timezone.now()
        )
        if (
            not is_past_confirmed
            and timezone.localtime(starts_at).date() < timezone.localdate()
        ):
            self.add_error(
                "starts_at",
                "Reservations cannot be moved to a past date.",
            )
        if ends_at <= starts_at:
            self.add_error("ends_at", "End time must be after start time.")
            return cleaned_data
        if (
            is_past_confirmed
            and ends_at != self.instance.ends_at
            and ends_at < self.instance.ends_at
        ):
            self.add_error(
                "ends_at",
                "The end time must be later than the booking's current end time.",
            )
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
        labels = {"unit_cost": "Unit cost (₱)"}

    def clean_unit_cost(self):
        unit_cost = self.cleaned_data.get("unit_cost")
        if unit_cost is not None and unit_cost < 0:
            raise forms.ValidationError("Unit cost cannot be negative.")
        return unit_cost


class InventoryItemDetailsForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = ("sku", "reorder_level", "unit_cost")
        widgets = {
            "sku": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "autocomplete": "off",
                }
            ),
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
        }
        labels = {
            "sku": "SKU",
            "reorder_level": "Reorder level",
            "unit_cost": "Unit cost (₱)",
        }

    def clean_sku(self):
        return self.cleaned_data["sku"] or None

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
        labels = {"purchase_cost": "Purchase cost (₱)"}

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
        label="Purchase cost per unit (₱)",
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

    def __init__(self, *args, branch, can_manage=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inventory"].queryset = Inventory.objects.filter(
            branch=branch
        ).order_by("name")
        self.fields["inventory"].label_from_instance = lambda item: item.name
        if not can_manage:
            self.fields["transaction_type"].choices = (
                (
                    InventoryTransaction.Type.CONSUMED,
                    InventoryTransaction.Type.CONSUMED.label,
                ),
            )
            self.fields["transaction_type"].initial = (
                InventoryTransaction.Type.CONSUMED
            )

    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get("transaction_type")
        quantity = cleaned_data.get("quantity")

        if transaction_type == InventoryTransaction.Type.ADJUSTMENT:
            if not cleaned_data.get("notes", "").strip():
                self.add_error(
                    "notes",
                    "A note is required for adjustments.",
                )

        if transaction_type == InventoryTransaction.Type.ADJUSTMENT:
            if quantity is not None:
                cleaned_data["target_quantity"] = quantity
        elif transaction_type == InventoryTransaction.Type.CONSUMED:
            if quantity is not None and quantity > 0:
                cleaned_data["quantity_change"] = -quantity
        elif transaction_type == InventoryTransaction.Type.RECEIVED:
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

    def __init__(self, *args, branch, can_manage=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = InventoryAsset.objects.filter(
            branch=branch
        ).order_by("name")
        if not can_manage:
            self.fields["event_type"].choices = tuple(
                choice
                for choice in self.ASSET_EVENT_CHOICES
                if choice[0]
                not in {
                    InventoryAssetHistory.Event.RETIRED,
                    InventoryAssetHistory.Event.DISPOSED,
                }
            )
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
