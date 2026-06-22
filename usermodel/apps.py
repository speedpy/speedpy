from django.apps import AppConfig


class UsermodelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usermodel'

    def ready(self):
        import usermodel.signals  # noqa: F401
