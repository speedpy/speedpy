from django.contrib import admin

from demoapp.models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "status", "price", "inventory")
    list_filter = ("category", "status")
    search_fields = ("name", "sku")
