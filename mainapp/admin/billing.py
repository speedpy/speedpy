from django.contrib import admin

from mainapp.models import BillingCustomer, BillingSubscription, BillingEventLog


@admin.register(BillingCustomer)
class BillingCustomerAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "provider_customer_id",
        "billable_type",
        "billable_id",
        "email",
        "created_at",
    )
    list_filter = ("provider", "billable_type")
    search_fields = ("provider_customer_id", "email", "billable_id")
    readonly_fields = ("raw_data", "created_at", "updated_at")


@admin.register(BillingSubscription)
class BillingSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "provider_subscription_id",
        "billable_type",
        "billable_id",
        "plan_key",
        "billing_interval",
        "status",
        "current_period_ends_at",
        "created_at",
    )
    list_filter = ("provider", "status", "plan_key", "billable_type")
    search_fields = (
        "provider_subscription_id",
        "provider_customer_id",
        "billable_id",
    )
    readonly_fields = ("raw_payload", "created_at", "updated_at")


@admin.register(BillingEventLog)
class BillingEventLogAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "event_type", "processed_at", "created_at")
    list_filter = ("provider", "event_type")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("payload", "processed_at", "created_at", "updated_at")
