# Project Guidelines

## Reservation and Calendar model contract

The scheduling domain uses two connected models:

- `Reservation` (`dashboard/models/reservations.py`) owns the guest-facing booking data:
  guest, facility, start/end times, party size, requests, status, amount, discount, and timestamps.
- `Calendar` (`dashboard/models/reservations.py`) owns scheduling and operational state for each occupied or unavailable time block.
- A confirmed booking has a one-to-one `Calendar` entry through `Reservation.calendar_entry`.
- `Calendar.reservation` may be `null`; such entries represent unavailable time blocks and must not be treated as bookings.

### Status ownership

- `Reservation.status` uses only `pending`, `confirmed`, or `declined`.
- `Calendar.status` uses `confirmed`, `cancelled`, `completed`, or `unavailable`.
- Keep these status domains separate. Do not write a Calendar status into `Reservation.status`.
- Every Reservation linked to a Calendar entry must have `Reservation.status == confirmed`, regardless of whether the Calendar status is confirmed, cancelled, or completed.
- For pending or declined reservations, edit the form using Reservation statuses and do not create or update a Calendar entry.
- For confirmed reservations, edit the form using Calendar statuses and preserve `Reservation.status == confirmed`.
- `Calendar.Status.UNAVAILABLE` is invalid for reservation-backed entries.
- For an end date that is not passed (`ends_at >= timezone.now()`), hide and reject `Confirmed`; normally `Cancelled` and `Completed` remain valid for confirmed reservations.
- When a Reservation is confirmed and its end date is not passed, hide and reject both `Confirmed` and `Completed` in the edit form. This applies regardless of the linked Calendar entry's current status.
- Passed confirmed reservations may show `Confirmed`, `Cancelled`, or `Completed`; they must never show `Unavailable`.

### Effective status

Use `Reservation.current_status` when code needs the user-visible state. It returns the linked Calendar status when present, otherwise it returns the Reservation status. Do not replace `Reservation.status` with `Calendar.status` as a workaround for cancellation or completion.

### Editing and routing rules

- Reservation and booking edits must use:
  `/dashboard/<branch>/reservations/<reservation_id>/edit/`
- Unavailable calendar entries with `reservation_id=None` use the dedicated calendar edit endpoint.
- Reservation-backed Calendar entries must redirect to the reservation edit endpoint instead of being edited through the unavailable-calendar form.
- Do not merge the Reservation and Calendar edit forms; they remain separate because they have different models, fields, and validation rules.
- Calendar operations still form part of a confirmed reservation edit: synchronize facility, start/end times, and notes between the Reservation and its linked Calendar entry.
- When a confirmed reservation edit has no linked Calendar entry, create one while keeping the Reservation confirmed.
- When editing a confirmed reservation, use `form.save(commit=False)`, assign `Reservation.status = Reservation.Status.CONFIRMED`, then save, and apply the selected Calendar status to the linked entry.

### Calendar synchronization

- `Calendar.Status.CONFIRMED`: keep the Reservation confirmed and decline conflicting pending reservations as needed.
- `Calendar.Status.CANCELLED`: keep the Reservation confirmed and cancel pending payments for that reservation.
- `Calendar.Status.COMPLETED`: keep the Reservation confirmed and do not require an unavailable or Cancelled Calendar value.
- `Calendar.save()` forces `status=UNAVAILABLE` and clears the booking reference when `reservation=None`.
- Enforce these rules in both form rendering and server-side validation.
- Protect writes with transactions when Reservation and Calendar records must change together.
