from datetime import timedelta, timezone as datetime_timezone

from django import forms
from django.utils import timezone

from dashboard.views.create_reservation import get_package_end


class PublicReservationForm(forms.Form):
    RATE_CHOICES = (
        ("24hours", "24-hour rate"),
        ("22hours", "22-hour rate"),
        ("morning", "Morning rate · 8 AM–5 PM"),
        ("evening", "Evening rate · 7 PM–6 AM"),
    )

    facility = forms.ModelChoiceField(
        queryset=None,
        empty_label="Choose a facility",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    rate_package = forms.ChoiceField(
        choices=RATE_CHOICES,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.HiddenInput(
            attrs={"data-start-input": ""},
        ),
    )
    ends_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.HiddenInput(attrs={"data-end-input": ""}),
    )
    days = forms.IntegerField(
        required=False,
        min_value=1,
        initial=1,
        widget=forms.NumberInput(
            attrs={
                "class": "input input-bordered w-full",
                "min": 1,
                "data-days-input": "",
            }
        ),
    )
    party_size = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=2147483647,
        initial=1,
        widget=forms.NumberInput(
            attrs={
                "class": "input input-bordered w-full",
                "min": 1,
                "step": 1,
                "data-party-size-input": "",
            }
        ),
        label="Number of guests",
    )
    special_requests = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "class": "textarea textarea-bordered w-full",
                "rows": 4,
                "placeholder": "Let us know about any requests for your stay.",
            }
        ),
    )

    def __init__(
        self,
        *args,
        facilities,
        allow_extra_hours=False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["facility"].queryset = facilities
        self.allow_extra_hours = allow_extra_hours
        if allow_extra_hours:
            self.fields["ends_at"].required = True
            self.fields["ends_at"].widget = forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "input input-bordered w-full",
                    "type": "datetime-local",
                    "data-end-input": "",
                },
            )

    def clean_starts_at(self):
        starts_at = self.cleaned_data["starts_at"]
        if timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at)
        if timezone.localtime(starts_at).date() < timezone.localdate():
            raise forms.ValidationError("Reservations cannot be made for past dates.")
        return starts_at

    def clean(self):
        cleaned_data = super().clean()
        facility = cleaned_data.get("facility")
        party_size = cleaned_data.get("party_size") or 1
        cleaned_data["party_size"] = party_size
        if facility is not None and not facility.has_capacity_for(party_size):
            self.add_error(
                "party_size",
                f"This facility can accommodate up to {facility.capacity} guests.",
            )

        starts_at = cleaned_data.get("starts_at")
        rate_package = cleaned_data.get("rate_package")
        if starts_at is None or rate_package is None:
            return cleaned_data

        days = cleaned_data.get("days") or 1
        if rate_package != "24hours":
            days = 1
            cleaned_data["days"] = 1
        ends_at = get_package_end(rate_package, starts_at, days)
        if ends_at is None:
            if rate_package == "morning":
                message = "Morning reservations must start at 8 AM."
            elif rate_package == "evening":
                message = "Evening reservations must start at 7 PM."
            else:
                message = "Choose a valid reservation rate and duration."
            self.add_error("starts_at", message)
            return cleaned_data

        if self.allow_extra_hours:
            requested_end = cleaned_data.get("ends_at")
            if requested_end is None:
                return cleaned_data
            duration = requested_end.astimezone(
                datetime_timezone.utc
            ) - starts_at.astimezone(datetime_timezone.utc)
            package_duration = ends_at.astimezone(
                datetime_timezone.utc
            ) - starts_at.astimezone(datetime_timezone.utc)
            extra_duration = duration - package_duration
            if (
                extra_duration < timedelta(0)
                or extra_duration % timedelta(hours=1) != timedelta(0)
            ):
                self.add_error(
                    "ends_at",
                    "The end time must be after the selected package and any "
                    "extension must use full-hour increments.",
                )
                return cleaned_data
            ends_at = requested_end

        cleaned_data["ends_at"] = ends_at
        return cleaned_data
