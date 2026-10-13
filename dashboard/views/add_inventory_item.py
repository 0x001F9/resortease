from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.forms import InventoryAssetCreateForm, InventoryItemCreateForm
from dashboard.models.inventory import InventoryTransaction
from dashboard.models.inventory_assets import InventoryAssetHistory


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class AddInventoryItemView(View):
    template_name = "inventory/add_item.html"

    def get_context_data(
        self,
        request,
        *,
        selected_type="stock",
        stock_form=None,
        asset_form=None,
    ):
        return {
            "title": "Add inventory item",
            "selected_type": selected_type,
            "stock_form": stock_form or InventoryItemCreateForm(),
            "asset_form": asset_form or InventoryAssetCreateForm(),
        }

    def get(self, request):
        selected_type = (
            "asset" if request.GET.get("type") == "asset" else "stock"
        )
        return render(
            request,
            self.template_name,
            self.get_context_data(request, selected_type=selected_type),
        )

    def post(self, request):
        item_type = request.POST.get("item_type")
        if item_type == "stock":
            stock_form = InventoryItemCreateForm(request.POST)
            if stock_form.is_valid():
                with transaction.atomic():
                    inventory_item = stock_form.save(commit=False)
                    inventory_item.branch = request.branch
                    inventory_item.quantity_on_hand = 0
                    inventory_item.save()

                    opening_quantity = stock_form.cleaned_data.get(
                        "opening_quantity"
                    ) or 0
                    if opening_quantity:
                        inventory_item.record_transaction(
                            transaction_type=InventoryTransaction.Type.RECEIVED,
                            quantity_change=opening_quantity,
                            performed_by=request.user,
                            reference="Opening stock",
                            notes="Initial stock recorded when item was created.",
                        )

                messages.success(
                    request,
                    f"{inventory_item.name} was added to inventory.",
                )
                return redirect("inventory", branch=request.branch.slug)

            return render(
                request,
                self.template_name,
                self.get_context_data(
                    request,
                    selected_type="stock",
                    stock_form=stock_form,
                ),
            )

        if item_type == "asset":
            asset_form = InventoryAssetCreateForm(request.POST)
            if asset_form.is_valid():
                with transaction.atomic():
                    asset = asset_form.save(commit=False)
                    asset.branch = request.branch
                    asset.save()
                    asset.record_event(
                        event_type=InventoryAssetHistory.Event.ACQUIRED,
                        performed_by=request.user,
                        notes="Asset registered in inventory.",
                    )

                messages.success(request, f"{asset.name} was added as an asset.")
                return redirect(
                    "inventory-asset-detail",
                    branch=request.branch.slug,
                    asset_id=asset.pk,
                )

            return render(
                request,
                self.template_name,
                self.get_context_data(
                    request,
                    selected_type="asset",
                    asset_form=asset_form,
                ),
            )

        return HttpResponseBadRequest("Choose stock item or tracked asset.")
