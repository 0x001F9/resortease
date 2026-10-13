from decimal import Decimal

from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
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
class InventoryAssetActivityView(View):
    template_name = "inventory/asset_activity.html"

    def get(self, request):
        asset_events = (
            InventoryAssetHistory.objects.filter(asset__branch=request.branch)
            .select_related("asset", "performed_by", "borrower")
            .order_by("-created_at")
        )
        return render(
            request,
            self.template_name,
            {
                "title": "Inventory asset activity",
                "asset_events": asset_events,
            },
        )