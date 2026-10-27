from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import TruncDay, TruncMonth
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from account.models import User
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.forms import ExpenseForm
from dashboard.models import (
    Branch,
    Calendar,
    Expense,
    Facility,
    Inventory,
    InventoryAsset,
    InventoryTransaction,
    Maintenance,
    Payment,
    Reservation,
)


def _local_day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _next_month_start(day):
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _guest_name(guest):
    return f"{guest.first_name} {guest.last_name}".strip() or guest.username


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class DashboardView(View):
    def get(self, request):
        now = timezone.localtime(timezone.now())
        today = now.date()
        month_start = _local_day_start(today.replace(day=1))
        next_month_start = _local_day_start(_next_month_start(today))
        year_start = _local_day_start(date(today.year, 1, 1))
        next_year_start = _local_day_start(date(today.year + 1, 1, 1))
        branch = request.branch

        branch_calendar = Calendar.objects.filter(
            facility__branch=branch,
            reservation__isnull=False,
        )
        bookings = (
            branch_calendar.filter(
                status=Calendar.Status.CONFIRMED,
            )
            .annotate(
                completion_priority=Case(
                    When(ends_at__lte=now, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .select_related("reservation__guest", "facility")
            .order_by("completion_priority", "starts_at")[:3]
        )
        active_reservations_count = branch_calendar.filter(
            status=Calendar.Status.CONFIRMED,
            starts_at__lte=now,
            ends_at__gt=now,
        ).count()

        month_completed_bookings = branch_calendar.filter(
            status=Calendar.Status.COMPLETED,
            ends_at__gte=month_start,
            ends_at__lt=next_month_start,
        ).count()
        month_payments = Payment.objects.filter(
            reservation_id__facility__branch=branch,
            status=Payment.Status.SUCCEEDED,
            paid_at__gte=month_start,
            paid_at__lt=next_month_start,
        )
        month_revenue = month_payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        monthly_revenue = (
            Payment.objects.filter(
                reservation_id__facility__branch=branch,
                status=Payment.Status.SUCCEEDED,
                paid_at__gte=year_start,
                paid_at__lt=next_year_start,
            )
            .annotate(month=TruncMonth("paid_at", tzinfo=timezone.get_current_timezone()))
            .values("month")
            .annotate(total=Sum("amount"))
        )
        revenue_by_month = {
            row["month"].month: float(row["total"])
            for row in monthly_revenue
        }

        overdue_assets = (
            InventoryAsset.objects.filter(
                branch=branch,
                status=InventoryAsset.Status.BORROWED,
                due_date__lt=now,
            )
            .select_related("borrowed_by")
            .order_by("due_date", "name")
        )
        low_stock_count = Inventory.objects.filter(
            branch=branch,
            quantity_on_hand__lte=F("reorder_level"),
        ).count()
        open_maintenance_count = Maintenance.objects.filter(
            facility__branch=branch,
            status__in=(Maintenance.Status.PENDING, Maintenance.Status.IN_PROGRESS),
        ).count()

        if now.hour < 12:
            greeting = "Good morning"
        elif now.hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        return render(
            request,
            "dashboard.html",
            {
                "greeting": greeting,
                "today": today,
                "now": now,
                "active_reservations_count": active_reservations_count,
                "bookings": bookings,
                "month_completed_bookings": month_completed_bookings,
                "month_revenue": month_revenue,
                "revenue_chart_data": {
                    "months": [
                        date(today.year, month, 1).strftime("%b")
                        for month in range(1, 13)
                    ],
                    "values": [
                        revenue_by_month.get(month, 0)
                        for month in range(1, 13)
                    ],
                },
                "overdue_assets": overdue_assets,
                "overdue_assets_count": overdue_assets.count(),
                "low_stock_count": low_stock_count,
                "open_maintenance_count": open_maintenance_count,
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class FinancialReportView(View):
    def get(self, request):
        return self.render_report(request, request.GET)

    def post(self, request):
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.branch = request.branch
            expense.recorded_by = request.user
            expense.save()
            return redirect(
                f"{request.path}?{request.GET.urlencode()}"
                if request.GET
                else request.path
            )
        return self.render_report(request, request.POST, expense_form=form)

    def render_report(self, request, params, expense_form=None):
        today = timezone.localdate()
        period = params.get(
            "period",
            "custom" if params.get("start_date") or params.get("end_date") else "month",
        )
        if period not in {"today", "week", "month", "year", "custom"}:
            return HttpResponseBadRequest("Date period is not supported.")
        if period == "today":
            default_start = today
            default_end = today
        elif period == "week":
            default_start = today - timedelta(days=today.weekday())
            default_end = today
        elif period == "year":
            default_start = today.replace(month=1, day=1)
            default_end = today
        elif period == "month":
            default_start = today.replace(day=1)
            default_end = today
        else:
            default_start = today.replace(day=1)
            default_end = today

        raw_start_date = params.get("start_date") if period == "custom" else None
        raw_end_date = params.get("end_date") if period == "custom" else None
        start_date = parse_date(raw_start_date) if raw_start_date else default_start
        end_date = parse_date(raw_end_date) if raw_end_date else default_end
        if raw_start_date and start_date is None:
            return HttpResponseBadRequest("Start date must use YYYY-MM-DD format.")
        if raw_end_date and end_date is None:
            return HttpResponseBadRequest("End date must use YYYY-MM-DD format.")
        if start_date > end_date:
            return HttpResponseBadRequest("Start date must not be after end date.")

        can_view_all_branches = (
            request.user.is_user_superuser
            or request.user.role == User.Role.GeneralManager
        )
        selected_branch_slug = params.get("branch", request.branch.slug)
        selected_branch = None
        if selected_branch_slug == "all":
            if not can_view_all_branches:
                raise Http404
        else:
            selected_branch = get_object_or_404(
                request.branches,
                slug=selected_branch_slug,
            )

        start_at = _local_day_start(start_date)
        end_at = _local_day_start(end_date + timedelta(days=1))
        branch_payments = Payment.objects.filter(
            reservation_id__facility__branch__in=request.branches
        ).select_related(
            "reservation_id__guest",
            "reservation_id__facility",
            "reservation_id__calendar_entry",
        )
        if selected_branch is not None:
            branch_payments = branch_payments.filter(
                reservation_id__facility__branch=selected_branch
            )

        successful_payments = branch_payments.filter(
            status=Payment.Status.SUCCEEDED,
            paid_at__gte=start_at,
            paid_at__lt=end_at,
        )
        payments_collected = (
            successful_payments.aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        refunds = branch_payments.filter(
            status=Payment.Status.REFUNDED,
            updated_at__gte=start_at,
            updated_at__lt=end_at,
        )
        refunds_total = (
            refunds.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )

        completed_reservations = Reservation.objects.filter(
            facility__branch__in=request.branches,
            calendar_entry__status=Calendar.Status.COMPLETED,
            calendar_entry__ends_at__gte=start_at,
            calendar_entry__ends_at__lt=end_at,
        )
        if selected_branch is not None:
            completed_reservations = completed_reservations.filter(
                facility__branch=selected_branch
            )

        gross_revenue = Decimal("0.00")
        discounts = Decimal("0.00")
        net_revenue = Decimal("0.00")
        unpriced_reservations = 0
        completed_refunds = (
            Payment.objects.filter(
                reservation_id__in=completed_reservations,
                status=Payment.Status.REFUNDED,
            )
            .values("reservation_id")
            .annotate(total=Sum("amount"))
        )
        refunds_by_reservation = {
            row["reservation_id"]: row["total"] or Decimal("0.00")
            for row in completed_refunds
        }
        revenue_categories = defaultdict(
            lambda: {
                "count": 0,
                "gross": Decimal("0.00"),
                "discounts": Decimal("0.00"),
                "refunds": Decimal("0.00"),
                "net": Decimal("0.00"),
            }
        )
        revenue_dates = defaultdict(
            lambda: {
                "count": 0,
                "gross": Decimal("0.00"),
                "discounts": Decimal("0.00"),
                "refunds": Decimal("0.00"),
                "net": Decimal("0.00"),
            }
        )
        branch_revenue_totals = defaultdict(lambda: Decimal("0.00"))
        for reservation in completed_reservations.select_related(
            "facility__branch",
            "calendar_entry",
        ).iterator():
            if reservation.raw_amount is None or reservation.raw_amount < 0:
                unpriced_reservations += 1
                continue
            gross = reservation.raw_amount
            discount = min(max(reservation.discount, Decimal("0.00")), gross)
            refund = refunds_by_reservation.get(
                reservation.pk, Decimal("0.00")
            )
            net = max(gross - discount - refund, Decimal("0.00"))
            gross_revenue += gross
            discounts += discount
            net_revenue += net
            category = reservation.facility.facility_type
            category_totals = revenue_categories[category]
            category_totals["count"] += 1
            category_totals["gross"] += gross
            category_totals["discounts"] += discount
            category_totals["refunds"] += refund
            category_totals["net"] += net
            service_date = timezone.localtime(
                reservation.calendar_entry.ends_at
            ).date()
            date_totals = revenue_dates[service_date]
            date_totals["count"] += 1
            date_totals["gross"] += gross
            date_totals["discounts"] += discount
            date_totals["refunds"] += refund
            date_totals["net"] += net
            branch_revenue_totals[reservation.facility.branch.name] += net

        revenue_category_labels = dict(Facility.FacilityType.choices)
        revenue_by_category = [
            {
                "category": revenue_category_labels.get(category, category),
                **totals,
            }
            for category, totals in sorted(revenue_categories.items())
        ]
        revenue_by_date = [
            {"date": service_date, **totals}
            for service_date, totals in sorted(revenue_dates.items())
        ]
        branch_revenue = [
            {"branch_name": name, "total": total}
            for name, total in sorted(branch_revenue_totals.items())
        ]

        balance_reservations = Reservation.objects.filter(
            facility__branch__in=request.branches,
            ends_at__gte=start_at,
            ends_at__lt=end_at,
            raw_amount__isnull=False,
        ).filter(
            Q(calendar_entry__isnull=True)
            | Q(
                calendar_entry__status__in=(
                    Calendar.Status.CONFIRMED,
                    Calendar.Status.COMPLETED,
                )
            )
        )
        if selected_branch is not None:
            balance_reservations = balance_reservations.filter(
                facility__branch=selected_branch
            )
        reservation_payments = (
            branch_payments.filter(
                status__in=(Payment.Status.SUCCEEDED, Payment.Status.REFUNDED),
            )
            .values("reservation_id")
            .annotate(
                paid=Sum(
                    "amount",
                    filter=Q(status=Payment.Status.SUCCEEDED),
                ),
                refunded=Sum(
                    "amount",
                    filter=Q(status=Payment.Status.REFUNDED),
                ),
            )
        )
        refunded_by_reservation = {
            row["reservation_id"]: row["refunded"] or Decimal("0.00")
            for row in reservation_payments
        }
        net_paid_by_reservation = {
            row["reservation_id"]: (row["paid"] or Decimal("0.00"))
            - (row["refunded"] or Decimal("0.00"))
            for row in reservation_payments
        }
        outstanding_balances = Decimal("0.00")
        for reservation in balance_reservations.only(
            "id", "raw_amount", "discount"
        ).iterator():
            charge = max(
                reservation.raw_amount
                - min(
                    max(reservation.discount, Decimal("0.00")),
                    reservation.raw_amount,
                ),
                Decimal("0.00"),
            )
            paid_amount = max(
                net_paid_by_reservation.get(
                    reservation.pk, Decimal("0.00")
                ),
                Decimal("0.00"),
            )
            outstanding_balances += max(
                charge - paid_amount,
                Decimal("0.00"),
            )

        expenses = Expense.objects.filter(
            branch__in=request.branches,
            expense_date__gte=start_date,
            expense_date__lte=end_date,
        )
        if selected_branch is not None:
            expenses = expenses.filter(branch=selected_branch)
        operating_expenses = expenses.aggregate(total=Sum("amount"))["total"] or Decimal(
            "0.00"
        )
        expense_categories = (
            expenses.values("category")
            .annotate(total=Sum("amount"), count=Count("pk"))
            .order_by("category")
        )
        expense_category_labels = dict(Expense.Category.choices)
        expense_breakdown = [
            {
                "category": expense_category_labels.get(row["category"]),
                "total": row["total"],
                "count": row["count"],
            }
            for row in expense_categories
        ]

        transaction_at = Case(
            When(status=Payment.Status.REFUNDED, then=F("updated_at")),
            When(status=Payment.Status.SUCCEEDED, then=F("paid_at")),
            default=F("created_at"),
            output_field=DateTimeField(),
        )
        dated_payments = branch_payments.annotate(
            transaction_at=transaction_at
        ).filter(transaction_at__gte=start_at, transaction_at__lt=end_at)
        selected_category = params.get("transaction_category", "")
        selected_method = params.get("payment_method", "")
        selected_status = params.get("payment_status", "")
        selected_expense_category = ""
        if selected_category == "expenses":
            dated_payments = dated_payments.none()
        elif selected_category.startswith("expense:"):
            selected_expense_category = selected_category.removeprefix("expense:")
            if selected_expense_category not in Expense.Category.values:
                return HttpResponseBadRequest("Expense category is not supported.")
            dated_payments = dated_payments.none()
        elif selected_category not in {"", "reservations"}:
            return HttpResponseBadRequest("Transaction category is not supported.")
        if selected_method:
            dated_payments = dated_payments.filter(method=selected_method)
        if selected_status:
            if selected_status not in Payment.Status.values:
                return HttpResponseBadRequest("Payment status is not supported.")
            dated_payments = dated_payments.filter(status=selected_status)

        transaction_rows = [
            {
                "date": payment.transaction_at,
                "reference": payment.transaction_reference or f"PAY-{payment.pk}",
                "category": f"Reservation payment · {payment.name}",
                "related": (
                    f"Reservation #{payment.reservation_id_id} · "
                    f"{_guest_name(payment.reservation_id.guest)} · "
                    f"{payment.reservation_id.current_status_display}"
                ),
                "gross": (
                    Decimal("0.00")
                    if payment.status == Payment.Status.REFUNDED
                    else payment.amount
                ),
                "discount": Decimal("0.00"),
                "refund": (
                    payment.amount
                    if payment.status == Payment.Status.REFUNDED
                    else Decimal("0.00")
                ),
                "amount": (
                    payment.amount
                    if payment.status == Payment.Status.SUCCEEDED
                    else Decimal("0.00")
                ),
                "balance": None,
                "method": payment.method or "—",
                "status": payment.get_status_display(),
            }
            for payment in dated_payments
        ]
        if (
            selected_category not in {"expenses"}
            and not selected_expense_category
            and not selected_method
            and not selected_status
        ):
            for reservation in balance_reservations.select_related(
                "guest",
                "calendar_entry",
            ).iterator():
                charge = max(
                    reservation.raw_amount
                    - min(
                        max(reservation.discount, Decimal("0.00")),
                        reservation.raw_amount,
                    ),
                    Decimal("0.00"),
                )
                paid_amount = max(
                    net_paid_by_reservation.get(
                        reservation.pk, Decimal("0.00")
                    ),
                    Decimal("0.00"),
                )
                balance = max(charge - paid_amount, Decimal("0.00"))
                payment_status = (
                    "Paid"
                    if balance == 0
                    else "Partially paid"
                    if paid_amount > 0
                    else "Unpaid"
                )
                transaction_rows.append(
                    {
                        "date": reservation.ends_at,
                        "reference": (
                            str(reservation.calendar_entry.booking_reference)
                            if getattr(
                                reservation,
                                "calendar_entry",
                                None,
                            )
                            and reservation.calendar_entry.booking_reference
                            else f"RES-{reservation.pk}"
                        ),
                        "category": "Reservation charge",
                        "related": (
                            f"Reservation #{reservation.pk} · "
                            f"{_guest_name(reservation.guest)} · "
                            f"{reservation.current_status_display}"
                        ),
                        "gross": reservation.raw_amount,
                        "discount": min(
                            max(reservation.discount, Decimal("0.00")),
                            reservation.raw_amount,
                        ),
                        "refund": refunded_by_reservation.get(
                            reservation.pk, Decimal("0.00")
                        ),
                        "amount": paid_amount,
                        "balance": balance,
                        "method": "—",
                        "status": payment_status,
                    }
                )
        display_expenses = expenses
        if selected_expense_category:
            display_expenses = display_expenses.filter(
                category=selected_expense_category
            )
        if (
            selected_category != "reservations"
            and not selected_method
            and not selected_status
        ):
            transaction_rows.extend(
                {
                    "date": expense.expense_date,
                    "reference": expense.reference or f"EXP-{expense.pk}",
                    "category": expense.get_category_display(),
                    "related": expense.description,
                    "gross": expense.amount,
                    "discount": Decimal("0.00"),
                    "refund": Decimal("0.00"),
                    "amount": expense.amount,
                    "is_expense": True,
                    "balance": None,
                    "method": "—",
                    "status": "Recorded",
                }
                for expense in display_expenses
            )
        transaction_rows.sort(
            key=lambda row: (
                timezone.localtime(row["date"]).date()
                if isinstance(row["date"], datetime)
                else row["date"],
                timezone.localtime(row["date"]).time()
                if isinstance(row["date"], datetime)
                else time.min,
            ),
            reverse=True,
        )
        transaction_page = Paginator(transaction_rows, 25).get_page(
            params.get("page", 1)
        )
        pagination_query = urlencode(
            {
                "period": period,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "branch": selected_branch_slug,
                "transaction_category": selected_category,
                "payment_method": selected_method,
                "payment_status": selected_status,
            }
        )
        payment_methods = (
            branch_payments.exclude(method="")
            .values_list("method", flat=True)
            .distinct()
            .order_by("method")
        )

        inventory_transactions = InventoryTransaction.objects.filter(
            inventory__branch__in=request.branches,
            created_at__gte=start_at,
            created_at__lt=end_at,
        ).select_related("inventory")
        if selected_branch is not None:
            inventory_transactions = inventory_transactions.filter(
                inventory__branch=selected_branch
            )
        inventory_movement_rows = defaultdict(
            lambda: {"received": 0, "consumed": 0, "returned": 0, "adjustment": 0}
        )
        inventory_purchase_cost = Decimal("0.00")
        for movement in inventory_transactions.iterator():
            key = movement.inventory.name
            inventory_movement_rows[key][movement.transaction_type] += (
                movement.quantity_change
            )
            if (
                movement.transaction_type == InventoryTransaction.Type.RECEIVED
                and movement.unit_cost is not None
            ):
                inventory_purchase_cost += (
                    movement.unit_cost * movement.quantity_change
                )

        monthly_revenue = (
            successful_payments.annotate(
                month=TruncMonth("paid_at", tzinfo=timezone.get_current_timezone())
            )
            .values("month")
            .annotate(total=Sum("amount"))
            .order_by("month")
        )
        chart_period = (
            "day" if (end_date - start_date).days < 62 else "month"
        )
        if chart_period == "day":
            chart_dates = [
                start_date + timedelta(days=offset)
                for offset in range((end_date - start_date).days + 1)
            ]
            truncation = TruncDay
        else:
            chart_dates = []
            chart_month_date = start_date.replace(day=1)
            while chart_month_date <= end_date:
                chart_dates.append(chart_month_date)
                chart_month_date = _next_month_start(chart_month_date)
            truncation = TruncMonth
        chart_rows = (
            successful_payments.annotate(
                bucket=truncation(
                    "paid_at",
                    tzinfo=timezone.get_current_timezone(),
                )
            )
            .values("bucket")
            .annotate(
                total=Sum("amount"),
                reservations=Count("reservation_id", distinct=True),
                bookings=Count(
                    "reservation_id",
                    filter=Q(
                        reservation_id__calendar_entry__status__in=(
                            Calendar.Status.CONFIRMED,
                            Calendar.Status.COMPLETED,
                        )
                    ),
                    distinct=True,
                ),
            )
            .order_by("bucket")
        )
        chart_totals = {}
        chart_reservations = {}
        chart_bookings = {}
        for row in chart_rows:
            bucket_date = timezone.localtime(row["bucket"]).date()
            if chart_period == "month":
                bucket_date = bucket_date.replace(day=1)
            chart_totals[bucket_date] = float(row["total"])
            chart_reservations[bucket_date] = row["reservations"]
            chart_bookings[bucket_date] = row["bookings"]
        recognized_totals = defaultdict(lambda: Decimal("0.00"))
        for row in revenue_by_date:
            bucket_date = row["date"]
            if chart_period == "month":
                bucket_date = bucket_date.replace(day=1)
            recognized_totals[bucket_date] += row["net"]
        revenue_chart_data = {
            "labels": [
                bucket.strftime("%b %d" if chart_period == "day" else "%b %Y")
                for bucket in chart_dates
            ],
            "values": [
                chart_totals.get(bucket, 0)
                for bucket in chart_dates
            ],
            "recognized_values": [
                float(recognized_totals.get(bucket, Decimal("0.00")))
                for bucket in chart_dates
            ],
            "reservations": [
                chart_reservations.get(bucket, 0)
                for bucket in chart_dates
            ],
            "bookings": [
                chart_bookings.get(bucket, 0)
                for bucket in chart_dates
            ],
        }
        return render(
            request,
            "financial_reports.html",
            {
                "branches": request.branches,
                "selected_branch": selected_branch,
                "selected_branch_slug": selected_branch_slug,
                "show_all_branches": selected_branch_slug == "all",
                "can_view_all_branches": can_view_all_branches,
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "chart_period": chart_period,
                "revenue_chart_data": revenue_chart_data,
                "total_revenue": net_revenue,
                "gross_revenue": gross_revenue,
                "discounts": discounts,
                "payments_collected": payments_collected,
                "refunds_total": refunds_total,
                "outstanding_balances": outstanding_balances,
                "operating_expenses": operating_expenses,
                "expense_breakdown": expense_breakdown,
                "revenue_by_category": revenue_by_category,
                "revenue_by_date": revenue_by_date,
                "unpriced_reservations": unpriced_reservations,
                "profit_loss_complete": False,
                "cogs_available": False,
                "transaction_page": transaction_page,
                "pagination_query": pagination_query,
                "transaction_category": selected_category,
                "transaction_method": selected_method,
                "transaction_status": selected_status,
                "payment_methods": payment_methods,
                "payment_statuses": Payment.Status.choices,
                "expense_form": expense_form or ExpenseForm(),
                "expense_categories": Expense.Category.choices,
                "inventory_movement_rows": [
                    {"name": name, **values}
                    for name, values in sorted(inventory_movement_rows.items())
                ],
                "inventory_purchase_cost": inventory_purchase_cost,
                "monthly_revenue": monthly_revenue,
                "branch_revenue": branch_revenue,
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
class DashboardRedirectView(View):
    def get(self, request):
        if request.user.role == User.Role.OperationManager and not request.user.is_user_superuser:
            branches = Branch.objects.filter(manager_id=request.user).order_by("name")
        else:
            branches = Branch.objects.order_by("name")
        branch = branches.first()

        if branch is None:
            return render(request, "branch_null.html")

        return redirect("dashboard", branch=branch.slug)
