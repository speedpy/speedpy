import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=160, verbose_name="Name")),
                ("sku", models.CharField(max_length=64, unique=True, verbose_name="SKU")),
                (
                    "category",
                    models.CharField(
                        choices=[("software", "Software"), ("services", "Services"), ("hardware", "Hardware")],
                        default="software",
                        max_length=32,
                        verbose_name="Category",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("draft", "Draft"), ("archived", "Archived")],
                        default="draft",
                        max_length=32,
                        verbose_name="Status",
                    ),
                ),
                ("price", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Price")),
                ("inventory", models.PositiveIntegerField(default=0, verbose_name="Inventory")),
                ("description", models.TextField(blank=True, verbose_name="Description")),
            ],
            options={
                "ordering": ("name",),
            },
        ),
    ]
