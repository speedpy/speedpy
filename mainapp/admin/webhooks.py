from django.contrib import admin

from mainapp.models import WebhookEndpoint, WebhookDelivery


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "team", "is_active", "events", "created_at")
    list_filter = ("is_active", "team")
    search_fields = ("url", "name", "team__name")
    raw_id_fields = ("team",)
    readonly_fields = ("secret", "previous_secret", "secret_rotated_at", "previous_secret_expires_at", "created_at", "updated_at")


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "endpoint",
        "status",
        "attempts",
        "http_status_code",
        "created_at",
    )
    list_filter = ("status", "event_type")
    search_fields = ("event_id", "endpoint__url")
    raw_id_fields = ("endpoint",)
    readonly_fields = (
        "endpoint",
        "event_id",
        "event_type",
        "payload",
        "status",
        "attempts",
        "scheduled_at",
        "delivered_at",
        "http_status_code",
        "response_body",
        "error_message",
        "created_at",
        "updated_at",
    )
