from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
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
from dashboard.models import (
    Branch,
    Calendar,
    Inventory,
    InventoryAsset,
    Maintenance,
    Payment,
)


def _local_day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _next_month_start(day):
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


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
        today = timezone.localdate()
        chart_period = request.GET.get("chart_period", "year")
        if chart_period not in {"year", "month"}:
            return HttpResponseBadRequest("Chart period must be year or month.")
        try:
            chart_year = int(request.GET.get("chart_year", today.year))
            chart_month = int(request.GET.get("chart_month", today.month))
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Chart year and month must be numeric.")
        if not 1 <= chart_year < 9999:
            return HttpResponseBadRequest("Chart year must be between 1 and 9998.")
        if not 1 <= chart_month <= 12:
            return HttpResponseBadRequest("Chart month must be between 1 and 12.")

        default_start = today.replace(day=1)
        raw_start_date = request.GET.get("start_date")
        raw_end_date = request.GET.get("end_date")
        start_date = parse_date(raw_start_date) if raw_start_date else default_start
        end_date = parse_date(raw_end_date) if raw_end_date else today
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
        selected_branch_slug = request.GET.get("branch", request.branch.slug)
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
            reservation_id__facility__branch__in=request.branches,
            status=Payment.Status.SUCCEEDED,
        )
        if selected_branch is not None:
            branch_payments = branch_payments.filter(
                reservation_id__facility__branch=selected_branch
            )

        payments = branch_payments.filter(
            paid_at__gte=start_at,
            paid_at__lt=end_at,
        )

        total_revenue = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        monthly_revenue = (
            payments.annotate(
                month=TruncMonth("paid_at", tzinfo=timezone.get_current_timezone())
            )
            .values("month")
            .annotate(total=Sum("amount"))
            .order_by("month")
        )
        chart_start_date = (
            date(chart_year, 1, 1)
            if chart_period == "year"
            else date(chart_year, chart_month, 1)
        )
        chart_end_date = (
            date(chart_year + 1, 1, 1)
            if chart_period == "year"
            else _next_month_start(chart_start_date)
        )
        chart_payments = branch_payments.filter(
            paid_at__gte=_local_day_start(chart_start_date),
            paid_at__lt=_local_day_start(chart_end_date),
        )
        truncation = TruncMonth if chart_period == "year" else TruncDay
        chart_rows = (
            chart_payments.annotate(
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
            bucket = (
                row["bucket"].month
                if chart_period == "year"
                else row["bucket"].day
            )
            chart_totals[bucket] = float(row["total"])
            chart_reservations[bucket] = row["reservations"]
            chart_bookings[bucket] = row["bookings"]
        bucket_count = 12 if chart_period == "year" else (
            chart_end_date - chart_start_date
        ).days
        chart_labels = (
            [
                date(chart_year, month, 1).strftime("%b")
                for month in range(1, 13)
            ]
            if chart_period == "year"
            else [
                str(day)
                for day in range(1, bucket_count + 1)
            ]
        )
        revenue_chart_data = {
            "labels": chart_labels,
            "values": [
                chart_totals.get(bucket, 0)
                for bucket in range(1, bucket_count + 1)
            ],
            "reservations": [
                chart_reservations.get(bucket, 0)
                for bucket in range(1, bucket_count + 1)
            ],
            "bookings": [
                chart_bookings.get(bucket, 0)
                for bucket in range(1, bucket_count + 1)
            ],
        }
        branch_revenue = (
            payments.values(
                branch_name=F("reservation_id__facility__branch__name"),
            )
            .annotate(total=Sum("amount"))
            .order_by("branch_name")
        )

        return render(
            request,
            "financial_reports.html",
            {
                "branches": request.branches,
                "selected_branch": selected_branch,
                "selected_branch_slug": selected_branch_slug,
                "show_all_branches": selected_branch_slug == "all",
                "can_view_all_branches": can_view_all_branches,
                "start_date": start_date,
                "end_date": end_date,
                "chart_period": chart_period,
                "chart_year": chart_year,
                "chart_month": chart_month,
                "chart_month_label": date(
                    2000,
                    chart_month,
                    1,
                ).strftime("%B"),
                "chart_month_choices": [
                    {
                        "value": month,
                        "label": date(2000, month, 1).strftime("%B"),
                    }
                    for month in range(1, 13)
                ],
                "revenue_chart_data": revenue_chart_data,
                "total_revenue": total_revenue,
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
