from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from speedpycom.models import BaseModel


class Product(BaseModel):
    class Category(models.TextChoices):
        SOFTWARE = "software", _("Software")
        SERVICES = "services", _("Services")
        HARDWARE = "hardware", _("Hardware")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DRAFT = "draft", _("Draft")
        ARCHIVED = "archived", _("Archived")

    name = models.CharField(_("Name"), max_length=160)
    sku = models.CharField(_("SKU"), max_length=64, unique=True)
    category = models.CharField(
        _("Category"),
        max_length=32,
        choices=Category.choices,
        default=Category.SOFTWARE,
    )
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    price = models.DecimalField(_("Price"), max_digits=10, decimal_places=2)
    inventory = models.PositiveIntegerField(_("Inventory"), default=0)
    description = models.TextField(_("Description"), blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("demo_product_detail", kwargs={"pk": self.pk})

    @property
    def inventory_label(self):
        if self.inventory == 0:
            return _("Out of stock")
        if self.inventory < 10:
            return _("Low stock")
        return _("In stock")
