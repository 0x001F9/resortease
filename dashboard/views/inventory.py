from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.forms import InventoryAssetStatusForm
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