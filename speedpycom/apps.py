from django.apps import AppConfig


class SpeedpycomConfig(AppConfig):
    """App config for the vendored ``speedpycom`` package.

    Its one job today is to import the deploy-time system checks so their
    ``@register`` decorators run. The checks are inert unless ``MCP_ENABLED``.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "speedpycom"

    def ready(self):
        # Deploy-time system checks (registered on import).
        from . import checks  # noqa: F401
