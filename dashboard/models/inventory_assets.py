from django.db import models, transaction


class InventoryAsset(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        BORROWED = "borrowed", "Borrowed"
        IN_MAINTENANCE = "in_maintenance", "In maintenance"
        RETIRED = "retired", "Retired"
        DISPOSED = "disposed", "Disposed"

    branch = models.ForeignKey(
        "Branch",
        on_delete=models.CASCADE,
        related_name="inventory_assets",
    )
    facility = models.ForeignKey(
        "Facility",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_assets",
    )
    name = models.CharField(max_length=150)
    asset_tag = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=150, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    borrowed_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="borrowed_inventory_assets",
    )
    due_date = models.DateField(blank=True, null=True)
    purchase_date = models.DateField(blank=True, null=True)
    purchase_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_assets"
        ordering = ["name"]

    def __str__(self):
        return f"{self.asset_tag} - {self.name}"

    def record_event(
        self,
        *,
        event_type,
        performed_by=None,
        borrower=None,
        due_date=None,
        notes="",
    ):
        if self.pk is None:
            raise ValueError("Save the inventory asset before recording an event.")
        if event_type not in InventoryAssetHistory.Event.values:
            raise ValueError(f"Unsupported inventory asset event: {event_type}")

        with transaction.atomic():
            asset = InventoryAsset.objects.select_for_update().get(pk=self.pk)
            status_before = asset.status
            event_borrower = borrower
            event_due_date = due_date

            if event_type == InventoryAssetHistory.Event.BORROWED:
                if status_before != self.Status.ACTIVE:
                    raise ValueError("Only active inventory assets can be borrowed.")
                if borrower is None:
                    raise ValueError("A borrower must be specified.")
                asset.status = self.Status.BORROWED
                asset.borrowed_by = borrower
                asset.due_date = due_date
            elif event_type == InventoryAssetHistory.Event.RETURNED:
                if status_before != self.Status.BORROWED:
                    raise ValueError("Only borrowed inventory assets can be returned.")
                event_borrower = asset.borrowed_by
                event_due_date = asset.due_date
                asset.status = self.Status.ACTIVE
                asset.borrowed_by = None
                asset.due_date = None
            elif event_type == InventoryAssetHistory.Event.MAINTENANCE_STARTED:
                if status_before != self.Status.ACTIVE:
                    raise ValueError("Only active inventory assets can enter maintenance.")
                asset.status = self.Status.IN_MAINTENANCE
            elif event_type == InventoryAssetHistory.Event.MAINTENANCE_COMPLETED:
                if status_before != self.Status.IN_MAINTENANCE:
                    raise ValueError("Only assets in maintenance can complete maintenance.")
                asset.status = self.Status.ACTIVE
            elif event_type == InventoryAssetHistory.Event.RETIRED:
                if status_before not in {self.Status.ACTIVE, self.Status.IN_MAINTENANCE}:
                    raise ValueError("Only active or maintenance assets can be retired.")
                asset.status = self.Status.RETIRED
            elif event_type == InventoryAssetHistory.Event.DISPOSED:
                if status_before not in {
                    self.Status.ACTIVE,
                    self.Status.IN_MAINTENANCE,
                    self.Status.RETIRED,
                }:
                    raise ValueError("This inventory asset cannot be disposed in its current status.")
                asset.status = self.Status.DISPOSED

            asset.save(update_fields=["status", "borrowed_by", "due_date", "updated_at"])
            history = InventoryAssetHistory.objects.create(
                asset=asset,
                event_type=event_type,
                status_before=status_before,
                status_after=asset.status,
                performed_by=performed_by,
                borrower=event_borrower,
                due_date=event_due_date,
                notes=notes,
            )

        self.status = asset.status
        self.borrowed_by = asset.borrowed_by
        self.due_date = asset.due_date
        return history


class InventoryAssetHistory(models.Model):
    
    class Event(models.TextChoices):
        ACQUIRED = "acquired", "Acquired"
        BORROWED = "borrowed", "Borrowed"
        RETURNED = "returned", "Returned"
        MAINTENANCE_STARTED = "maintenance_started", "Maintenance started"
        MAINTENANCE_COMPLETED = "maintenance_completed", "Maintenance completed"
        RETIRED = "retired", "Retired"
        DISPOSED = "disposed", "Disposed"

    asset = models.ForeignKey(
        "InventoryAsset",
        on_delete=models.PROTECT,
        related_name="history",
    )
    event_type = models.CharField(max_length=30, choices=Event.choices)
    status_before = models.CharField(
        max_length=20,
        choices=InventoryAsset.Status.choices,
    )
    status_after = models.CharField(
        max_length=20,
        choices=InventoryAsset.Status.choices,
    )
    performed_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_asset_events",
    )
    borrower = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_asset_borrowing_history",
    )
    due_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_asset_history"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.asset.asset_tag}: {self.get_event_type_display()}"
