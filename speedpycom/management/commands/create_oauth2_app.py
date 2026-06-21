from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Register an OAuth2 application for CLI or MCP device-flow auth."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Human-readable application name")
        parser.add_argument(
            "--grant-type",
            choices=["device-code", "authorization-code"],
            default="device-code",
            help="OAuth2 grant type (default: device-code)",
        )
        parser.add_argument(
            "--redirect-uris",
            default="",
            help="Space-separated redirect URIs (authorization-code only)",
        )
        parser.add_argument(
            "--scopes",
            default="read:profile read:teams",
            help="Suggested scopes for clients to request (not stored on the app)",
        )

    def handle(self, *args, **options):
        try:
            from oauth2_provider.models import get_application_model
        except ImportError:
            raise CommandError(
                "django-oauth-toolkit is not installed. "
                "Install it with: pip install django-oauth-toolkit"
            )

        Application = get_application_model()

        name = options["name"]
        grant_type = options["grant_type"]

        if Application.objects.filter(name=name).exists():
            raise CommandError(f'Application "{name}" already exists.')

        grant_map = {
            "device-code": Application.GRANT_DEVICE_CODE,
            "authorization-code": Application.GRANT_AUTHORIZATION_CODE,
        }

        app = Application.objects.create(
            name=name,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=grant_map[grant_type],
            redirect_uris=options["redirect_uris"],
            skip_authorization=False,
        )

        self.stdout.write(self.style.SUCCESS(f"Created OAuth2 application: {name}"))
        self.stdout.write(f"  Client ID:  {app.client_id}")
        self.stdout.write(f"  Grant type: {grant_type}")
        self.stdout.write("")
        self.stdout.write(
            "Use this client_id in your CLI or MCP server configuration."
        )
        self.stdout.write(
            f"  Suggested scopes to request: {options['scopes']}"
        )
