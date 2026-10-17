from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.forms import (
    InventoryAssetMovementForm,
    InventoryAssetStatusForm,
    InventoryMovementForm,
)
from dashboard.models.inventory import Inventory, InventoryTransaction
from dashboard.models.inventory_assets import InventoryAsset, InventoryAssetHistory


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryView(View):
    template_name = "inventory/index.html"

    def get(self, request):
        inventory_items = list(
            Inventory.objects.filter(branch=request.branch).order_by("name")
        )

        low_stock_count = 0
        total_units_on_hand = 0
        total_stock_value = Decimal("0")

        for item in inventory_items:
            total_units_on_hand += item.quantity_on_hand
            if item.unit_cost is not None:
                total_stock_value += item.stock_value or Decimal("0")
            if item.quantity_on_hand <= item.reorder_level:
                low_stock_count += 1

        recent_transactions = (
            InventoryTransaction.objects.filter(inventory__branch=request.branch)
            .select_related("inventory")
            .order_by("-created_at")[:2]
        )
        inventory_assets = (
            InventoryAsset.objects.filter(branch=request.branch)
            .select_related("borrowed_by")
            .order_by("name")
        )
        overdue_assets_count = InventoryAsset.objects.filter(
            branch=request.branch,
            status=InventoryAsset.Status.BORROWED,
            due_date__isnull=False,
            due_date__lte=timezone.now(),
        ).count()
        recent_asset_events = (
            InventoryAssetHistory.objects.filter(asset__branch=request.branch)
            .select_related("asset", "performed_by", "borrower")
            .order_by("-created_at")[:2]
        )

        return render(
            request,
            self.template_name,
            {
                "title": "Inventory",
                "inventory_items": inventory_items,
                "total_items": len(inventory_items),
                "total_units_on_hand": total_units_on_hand,
                "low_stock_count": low_stock_count,
                "total_stock_value": total_stock_value,
                "recent_transactions": recent_transactions,
                "inventory_assets": inventory_assets,
                "inventory_assets_count": inventory_assets.count(),
                "overdue_assets_count": overdue_assets_count,
                "recent_asset_events": recent_asset_events,
                "inventory_count_by_status": {
                    "healthy": sum(
                        1
                        for item in inventory_items
                        if item.quantity_on_hand > item.reorder_level
                    ),
                    "low": low_stock_count,
                    "zero": sum(
                        1
                        for item in inventory_items
                        if item.quantity_on_hand == 0
                    ),
                },
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventorySearchView(View):
    template_name = "inventory/search.html"
    ITEM_TYPE_CHOICES = {"all", "items", "assets"}

    def get(self, request):
        query = request.GET.get("q", "").strip()
        item_type = request.GET.get("type", "all")
        if item_type not in self.ITEM_TYPE_CHOICES:
            item_type = "all"

        results = []
        if item_type in {"all", "items"}:
            items = Inventory.objects.filter(branch=request.branch)
            if query:
                items = items.filter(
                    Q(name__icontains=query)
                    | Q(sku__icontains=query)
                    | Q(notes__icontains=query)
                )
            results.extend(
                {"type": "item", "item": item, "name": item.name}
                for item in items
            )

        if item_type in {"all", "assets"}:
            assets = InventoryAsset.objects.filter(branch=request.branch).select_related(
                "borrowed_by"
            )
            if query:
                assets = assets.filter(
                    Q(name__icontains=query)
                    | Q(asset_tag__icontains=query)
                    | Q(category__icontains=query)
                    | Q(brand__icontains=query)
                    | Q(serial_number__icontains=query)
                )
            results.extend(
                {"type": "asset", "asset": asset, "name": asset.name}
                for asset in assets
            )

        results.sort(key=lambda result: result["name"].casefold())
        return render(
            request,
            self.template_name,
            {
                "title": "Search inventory",
                "query": query,
                "item_type": item_type,
                "results": results,
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryTransactionsView(View):
    template_name = "inventory/transactions.html"

    def get(self, request):
        transactions = (
            InventoryTransaction.objects.filter(inventory__branch=request.branch)
            .select_related("inventory", "performed_by")
            .order_by("-created_at")
        )
        return render(
            request,
            self.template_name,
            {
                "title": "Inventory transactions",
                "transactions": transactions,
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class RecordInventoryMovementView(View):
    template_name = "inventory/record_movement.html"

    def get_context(self, request, selected_type, inventory_form=None, asset_form=None):
        branch_assets = InventoryAsset.objects.filter(branch=request.branch).order_by(
            "name"
        )
        inventory_form = inventory_form or InventoryMovementForm(
            branch=request.branch
        )
        return {
            "title": "Record inventory movement",
            "selected_type": selected_type,
            "inventory_form": inventory_form,
            "inventory_quantities": list(
                inventory_form.fields["inventory"].queryset.values(
                    "id",
                    "quantity_on_hand",
                )
            ),
            "asset_form": asset_form
            or InventoryAssetMovementForm(branch=request.branch),
            "asset_status_events": {
                status.value: list(
                    InventoryAssetMovementForm.events_for_status(status.value)
                )
                for status in InventoryAsset.Status
            },
            "asset_statuses": list(branch_assets.values("id", "status")),
            "hide_aside": True,
        }

    def get(self, request):
        selected_type = (
            "asset" if request.GET.get("type") == "asset" else "inventory"
        )
        return render(
            request,
            self.template_name,
            self.get_context(request, selected_type),
        )

    def post(self, request):
        selected_type = request.POST.get("item_type")
        if selected_type == "inventory":
            form = InventoryMovementForm(request.POST, branch=request.branch)
            if form.is_valid():
                item = form.cleaned_data["inventory"]
                if (
                    form.cleaned_data["transaction_type"]
                    == InventoryTransaction.Type.ADJUSTMENT
                ):
                    transaction_data = {
                        "target_quantity": form.cleaned_data["target_quantity"]
                    }
                else:
                    transaction_data = {
                        "quantity_change": form.cleaned_data["quantity_change"]
                    }
                try:
                    item.record_transaction(
                        transaction_type=form.cleaned_data["transaction_type"],
                        **transaction_data,
                        performed_by=request.user,
                        unit_cost=form.cleaned_data["unit_cost"],
                        reference=(
                            f"INV-{timezone.localdate():%Y%m%d}-"
                            f"{uuid4().hex[:8].upper()}"
                        ),
                        notes=form.cleaned_data["notes"],
                    )
                except ValueError as error:
                    form.add_error(None, str(error))
                else:
                    messages.success(
                        request,
                        f"Recorded a movement for {item.name}.",
                    )
                    return redirect(
                        "inventory-item-detail",
                        branch=request.branch.slug,
                        item_id=item.pk,
                    )

                return render(
                    request,
                    self.template_name,
                    self.get_context(
                        request,
                        selected_type,
                        inventory_form=form,
                    ),
                )

            return render(
                request,
                self.template_name,
                self.get_context(
                    request,
                    selected_type,
                    inventory_form=form,
                ),
            )

        if selected_type == "asset":
            form = InventoryAssetMovementForm(request.POST, branch=request.branch)
            if form.is_valid():
                asset = form.cleaned_data["asset"]
                try:
                    asset.record_event(
                        event_type=form.cleaned_data["event_type"],
                        performed_by=request.user,
                        borrower=form.cleaned_data["borrower"],
                        due_date=form.cleaned_data["due_date"],
                        notes=form.cleaned_data["notes"],
                    )
                except ValueError as error:
                    asset.refresh_from_db()
                    form = InventoryAssetMovementForm(
                        request.POST,
                        branch=request.branch,
                    )
                    form.add_error(None, str(error))
                else:
                    messages.success(
                        request,
                        f"Recorded a history event for {asset.name}.",
                    )
                    return redirect(
                        "inventory-asset-detail",
                        branch=request.branch.slug,
                        asset_id=asset.pk,
                    )

                return render(
                    request,
                    self.template_name,
                    self.get_context(
                        request,
                        selected_type,
                        asset_form=form,
                    ),
                )

            return render(
                request,
                self.template_name,
                self.get_context(
                    request,
                    selected_type,
                    asset_form=form,
                ),
            )

        return HttpResponseBadRequest("Choose inventory items or assets.")


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryAssetActivityView(View):
    template_name = "inventory/asset_activity.html"

    def get(self, request):
        asset_events = (
            InventoryAssetHistory.objects.filter(asset__branch=request.branch)
            .select_related("asset", "performed_by", "borrower")
            .order_by("-created_at")
        )
        overdue_assets = (
            InventoryAsset.objects.filter(
                branch=request.branch,
                status=InventoryAsset.Status.BORROWED,
                due_date__isnull=False,
                due_date__lte=timezone.now(),
            )
            .select_related("borrowed_by")
            .order_by("due_date", "name")
        )
        return render(
            request,
            self.template_name,
            {
                "title": "Inventory asset activity",
                "asset_events": asset_events,
                "overdue_assets": overdue_assets,
            },
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryItemDetailView(View):
    template_name = "inventory/item_detail.html"

    def get_item(self, request, item_id):
        return get_object_or_404(
            Inventory.objects.select_related("branch"),
            pk=item_id,
            branch=request.branch,
        )

    def get_context(self, item):
        transactions = item.transactions.select_related("performed_by").order_by(
            "-created_at"
        )
        return {
            "title": item.name,
            "item": item,
            "transactions": transactions,
            "hide_aside": True,
        }

    def get(self, request, item_id):
        item = self.get_item(request, item_id)
        return render(
            request,
            self.template_name,
            self.get_context(item),
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryTransactionDetailView(View):
    template_name = "inventory/transaction_detail.html"

    def get_transaction(self, request, transaction_id):
        return get_object_or_404(
            InventoryTransaction.objects.select_related("inventory", "performed_by"),
            pk=transaction_id,
            inventory__branch=request.branch,
        )

    def get_context(self, transaction):
        return {
            "title": f"{transaction.inventory.name} transaction",
            "transaction": transaction,
            "hide_aside": True,
        }

    def get(self, request, transaction_id):
        transaction = self.get_transaction(request, transaction_id)
        return render(
            request,
            self.template_name,
            self.get_context(transaction),
        )


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryAssetDetailView(View):
    template_name = "inventory/asset_detail.html"

    def get_asset(self, request, asset_id):
        return get_object_or_404(
            InventoryAsset.objects.select_related("borrowed_by"),
            pk=asset_id,
            branch=request.branch,
        )

    def get_context(self, asset, form=None):
        asset_events = asset.history.select_related(
            "performed_by",
            "borrower",
        )
        return {
            "title": asset.name,
            "asset": asset,
            "asset_events": asset_events,
            "status_form": form or InventoryAssetStatusForm(asset=asset),
            "hide_aside": True,
        }

    def get(self, request, asset_id):
        asset = self.get_asset(request, asset_id)
        return render(
            request,
            self.template_name,
            self.get_context(asset),
        )

    def post(self, request, asset_id):
        asset = self.get_asset(request, asset_id)
        form = InventoryAssetStatusForm(request.POST, asset=asset)
        if not form.fields:
            return HttpResponseBadRequest(
                "This asset has no available status changes."
            )
        if form.is_valid():
            try:
                asset.record_event(
                    event_type=form.event_type,
                    performed_by=request.user,
                    notes=form.cleaned_data["notes"],
                )
            except ValueError as error:
                asset.refresh_from_db()
                form = InventoryAssetStatusForm(request.POST, asset=asset)
                form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    f"{asset.name} status changed to {asset.get_status_display()}.",
                )
                return redirect(
                    "inventory-asset-detail",
                    branch=request.branch.slug,
                    asset_id=asset.pk,
                )

        asset.refresh_from_db()
        return render(
            request,
            self.template_name,
            self.get_context(asset, form),
        )