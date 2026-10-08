from django.db import models, transaction
from django.db.models import F, Q


class Inventory(models.Model):
    class Unit(models.TextChoices):
        PIECE = "piece", "Piece"
        BOTTLE = "bottle", "Bottle"
        CAN = "can", "Can"
        PACK = "pack", "Pack"
        BOX = "box", "Box"
        CASE = "case", "Case"
        SET = "set", "Set"
        ROLL = "roll", "Roll"
        GRAM = "g", "Gram"
        KILOGRAM = "kg", "Kilogram"
        MILLILITER = "ml", "Milliliter"
        LITER = "l", "Liter"

    branch = models.ForeignKey(
        "Branch",
        on_delete=models.CASCADE,
        related_name="inventory_items",
    )
    name = models.CharField(max_length=150, unique=True)
    sku = models.CharField(max_length=64, blank=True, null=True, unique=True)
    unit = models.CharField(max_length=20, choices=Unit.choices)
    quantity_on_hand = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Cost for one stocked unit, such as one 200 ml bottle.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory"
        ordering = ["name"]

    def __str__(self):
        return f"{self.branch.name} - {self.name}"

    @property
    def stock_value(self):
        if self.unit_cost is None:
            return None
        return self.unit_cost * self.quantity_on_hand

    def record_transaction(
        self,
        *,
        transaction_type,
        quantity_change,
        performed_by=None,
        unit_cost=None,
        reference="",
        notes="",
    ):
        if transaction_type not in InventoryTransaction.Type.values:
            raise ValueError(f"Unsupported inventory transaction type: {transaction_type}")
        if quantity_change == 0:
            raise ValueError("Inventory transaction quantity_change cannot be zero.")
        if (
            transaction_type
            in {InventoryTransaction.Type.RECEIVED, InventoryTransaction.Type.RETURNED}
            and quantity_change < 0
        ) or (
            transaction_type == InventoryTransaction.Type.CONSUMED
            and quantity_change > 0
        ):
            raise ValueError(
                "Received and returned quantities must be positive; consumed quantities must be negative."
            )

        with transaction.atomic():
            inventory = Inventory.objects.select_for_update().get(pk=self.pk)
            balance_before = inventory.quantity_on_hand
            balance_after = balance_before + quantity_change
            if balance_after < 0:
                raise ValueError("Inventory transaction would make stock negative.")

            inventory.quantity_on_hand = balance_after
            inventory.save(update_fields=["quantity_on_hand", "updated_at"])

            inventory_transaction = InventoryTransaction.objects.create(
                inventory=inventory,
                transaction_type=transaction_type,
                quantity_change=quantity_change,
                balance_before=balance_before,
                balance_after=balance_after,
                unit_cost=unit_cost if unit_cost is not None else inventory.unit_cost,
                performed_by=performed_by,
                reference=reference,
                notes=notes,
            )

        self.quantity_on_hand = balance_after
        return inventory_transaction


class InventoryTransaction(models.Model):
    class Type(models.TextChoices):
        RECEIVED = "received", "Received"
        CONSUMED = "consumed", "Consumed"
        RETURNED = "returned", "Returned"
        ADJUSTMENT = "adjustment", "Adjustment"

    inventory = models.ForeignKey(
        "Inventory",
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    quantity_change = models.IntegerField(
        help_text="Signed change in stocked units; for example, +5 received or -1 consumed.",
    )
    balance_before = models.PositiveIntegerField()
    balance_after = models.PositiveIntegerField()
    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Cost per stocked unit at the time of this transaction.",
    )
    performed_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    reference = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_transactions"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(quantity_change=0),
                name="inventory_transaction_nonzero_quantity",
            ),
            models.CheckConstraint(
                condition=Q(balance_after=F("balance_before") + F("quantity_change")),
                name="inventory_transaction_balance_matches",
            ),
            models.CheckConstraint(
                condition=(
                    Q(transaction_type="adjustment")
                    | Q(transaction_type="received", quantity_change__gt=0)
                    | Q(transaction_type="consumed", quantity_change__lt=0)
                    | Q(transaction_type="returned", quantity_change__gt=0)
                ),
                name="inventory_transaction_type_quantity_sign",
            ),
        ]

    def __str__(self):
        return f"{self.inventory.name}: {self.quantity_change:+d}"
