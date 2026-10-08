from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import F, Sum
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from account.decoration.role_required import normal_user_not_allowed
from dashboard.decorations.branch_check import check_branch_dashboard
from dashboard.models.inventory import Inventory, InventoryTransaction


@method_decorator(normal_user_not_allowed, name="dispatch")
@method_decorator(check_branch_dashboard, name="dispatch")
class InventoryView(View):
    template_name = "inventory/index.html"

    def get(self, request):
        return render(
            request,
            self.template_name
        )