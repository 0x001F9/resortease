from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Expense(models.Model):
    class Category(models.TextChoices):
        UTILITIES = "utilities", "Electricity and water"
        SALARIES = "salaries", "Salaries and wages"
        MAINTENANCE = "maintenance", "Maintenance and repairs"
        SUPPLIES = "supplies", "Cleaning supplies and consumables"
        OTHER = "other", "Other operating expenses"

    branch = models.ForeignKey(
        "dashboard.Branch",
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )
    expense_date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-pk"]

    def __str__(self):
        return f"{self.get_category_display()}: {self.amount}"
