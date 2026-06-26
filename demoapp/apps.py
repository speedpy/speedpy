"""SPEEDPY_DEMO: entire demoapp is demo content — remove before production."""

from django.apps import AppConfig


class DemoappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "demoapp"
