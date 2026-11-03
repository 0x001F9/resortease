# Financial Reports Data Audit

This document describes the data and calculations used by the financial reports page.
The page is database-backed; it does not generate mock totals.

## Report date range and branch selection

The report accepts `Today`, `This week`, `This month`, `This year`, or custom dates.
Custom start and end dates are inclusive. General managers and superusers may select
all branches; operation managers and other staff are limited to their authorized branches.

Relevant source:

- Report view: `dashboard/views/dashboard.py`, `FinancialReportView`
- Template: `dashboard/templates/financial_reports.html`
- Reservation model: `dashboard/models/reservations.py`
- Payment model: `dashboard/models/reservations.py`
- Inventory models: `dashboard/models/inventory.py`

## Summary cards

All monetary values displayed on the financial report use compact display formatting.
Values below 1,000 retain two decimal places; larger values use up to two decimal
places with K, M, B, or T suffixes. For example, 1,500,000 displays as 1.5M.

### Net recognized revenue

**Purpose:** Actual reservation payments retained for confirmed, cancelled, and completed reservations in the selected period. Revenue is attributed to the reservation's service end date, not the dates payments or refunds were recorded.

**Data source:**

- `Payment.amount` for successful and refunded payments
- `Reservation.discount` (reported separately; not deducted from payment amounts)
- Linked `Calendar.status` and `Calendar.ends_at`

**Calculation:**

```text
For each reservation with a recognized Calendar status:
  successful_payments = sum(payment.amount where status is succeeded)
  refunds = sum(payment.amount where status is refunded)
  net_retained = max(successful_payments - refunds, 0)

Net recognized revenue = sum(net_retained for recognized reservations)
```

Recognized reservations are selected when the linked `Calendar.status` is confirmed,
cancelled, or completed. The linked calendar end date is the recognition/service date.
The branch is taken from the reservation's facility. Successful payments already
reflect discounts, so reservation discounts are reported separately and are not
deducted again. For a cancelled reservation, the amount retained is its successful
payments less recorded refund payments; for example, a 50% refund leaves 50% of the
successful amount as net revenue.

Payments and refunds are matched to the reservation's service date for this metric,
even if they were recorded outside the selected date range. The separate
`Payments collected` and `Refunds recorded` cards use their own transaction dates.

### Payments collected

**Purpose:** Actual successful cash collected in the selected period.

**Data source:** `Payment` rows with status `succeeded` and a `paid_at` timestamp.

**Calculation:**

```text
Payments collected = sum(Payment.amount)
where status is succeeded
and paid_at is within the selected date range
```

This is a cash-payment figure and can differ from recognized revenue because stays
may be paid before or after their completion date.

### Total sold inventory

**Purpose:** Estimated inventory value moved through consumed transactions in the selected period.

**Data source:**

- `InventoryTransaction.transaction_type`
- `InventoryTransaction.quantity_change`
- `InventoryTransaction.unit_cost`
- `InventoryTransaction.created_at`
- `Inventory.branch`

Only consumed transactions within the selected date range and branch scope are included.
Transactions without a recorded unit cost are omitted.

**Calculation:**

```text
sold_amount = sum(unit_cost × abs(quantity_change))
for each consumed InventoryTransaction
```

## Discounts applied

**Data source:** `Reservation.discount` for confirmed, cancelled, and completed priced reservations.

**Calculation:**

```text
For each reservation:
  discount = min(max(reservation.discount, 0), reservation.raw_amount)

Discounts applied = sum(discount)
```

## Refunds recorded

**Data source:** `Payment` rows with status `refunded`.

**Calculation:**

```text
Refunds recorded = sum(Payment.amount)
where status is refunded
and updated_at is within the selected date range
```

The payment model stores the latest status and update time, not a complete historical
refund audit trail. This card's period therefore uses the refund's latest update date.

## Recognized revenue by facility category

**Data source:**

- Reservations with `Calendar.status` confirmed, cancelled, or completed
- `Facility.facility_type`
- Successful and refunded `Payment.amount` values
- `Reservation.discount` for the separate discount column

Rows are grouped by the facility type category. Each row contains reservation count,
successful payments, discounts, refunds, and net retained revenue. Discounts are
shown for reference but are already reflected in successful payment amounts.

**Calculation:**

```text
category net = sum(successful reservation payments - recorded reservation refunds)
```

## Recognized revenue by service date

**Data source:** Linked calendar entries whose status is confirmed, cancelled, or completed.

The service date is the local date of `Calendar.ends_at`.
The table groups successful payments, discounts, refunds, reservation count, and net
retained revenue by that date. Discounts are not subtracted a second time.

## Revenue and payment trend

**Purpose:** Compare reservation revenue retained by service date with successful cash receipts by payment date.

**Recognized revenue series:**

- Source: recognized reservation service end dates
- Value: successful reservation payments minus recorded refunds, grouped by day or month
- Grouping switches to month when the selected range is 62 days or longer

**Payment series:**

- Source: successful payment `paid_at` timestamps
- Value: sum of successful payment amounts
- Grouping switches to day or month with the same date-range rule as recognized revenue

The chart may show the two data series at different times. Net recognized revenue
follows the reservation calendar service end date for recognized statuses; payments
follow when the payment was recorded as successful.

## Monthly reservation payments collected

**Data source:** Successful `Payment` rows within the selected range.

**Calculation:**

```text
total for month = sum(successful payment amounts)
grouped by paid_at month
```

When viewing all branches, the page also shows net recognized revenue by branch.
Branch totals use successful payments less recorded refunds and are grouped by the
branch of each recognized reservation's facility.

## Store and inventory data

The current database has no POS sales records and no product selling-price records.
Therefore, the page does not calculate POS sales totals, best-selling products,
product margins, or cost of goods sold.

Inventory transaction rows are records of physical stock movements, not POS sales.

### Inventory movements

**Data source:** `InventoryTransaction` within the selected range.

For each inventory item, the table reports:

- Received: sum of signed received quantity changes
- Consumed: sum of signed consumed quantity changes
- Adjustments: sum of adjustment quantity changes

The movement table uses `quantity_change`, which is signed:

- Received transactions normally add positive quantities
- Consumed transactions normally add negative quantities
- Adjustments may add either positive or negative quantities

### Known received-stock cost

**Data source:** Received `InventoryTransaction` rows with a non-null `unit_cost`.

**Calculation:**

```text
Known received-stock cost =
  sum(unit_cost * positive quantity_change)
```

Movements without a recorded unit cost are omitted. This value is historical received
purchase cost, not cost of goods sold and not a profit calculation.

## Financial transactions

This section combines reservation charge and payment records.

| Row type | Date | Data source |
|---|---|---|
| Reservation charge | `Reservation.ends_at` | Reservation amount, discount, payments, and status |
| Successful/refunded payment | `paid_at` for successful payments; `updated_at` for refunds | `Payment` |

Reservation charge balance is calculated as:

```text
charge = max(raw_amount - capped discount, 0)
paid_amount = max(successful payment total - refunded payment total, 0)
balance = max(charge - paid_amount, 0)

status:
  Paid if balance is zero
  Partially paid if paid_amount is greater than zero
  Unpaid otherwise
```

Transactions can be filtered by category, payment method, and payment status.
Reservation charge rows and payment rows intentionally remain separate. The summary
cards should be treated as authoritative totals rather than totals recalculated by
summing the transaction table.

## Known limitations

- Successful payments and refund amounts in recognized revenue are matched by
  reservation, not by payment or refund date.
- Refund totals use each refund's latest `updated_at` date.
- A refunded payment has no separate refund-history table.
- Inventory consumption is not connected to facility or store sales.
- There is no POS sales table and no product sales-price or product-cost table.
- Gross profit, net profit, and cost of goods sold are not available.
- Payments or refunds recorded after the selected period can change net recognized
  revenue for a reservation whose service end date falls in that period.
- Net recognized revenue is payment-based and attributed to the service date; it is
  not a cash-flow total for the selected date range. Use Payments collected and
  Refunds recorded for transaction-date cash totals.
