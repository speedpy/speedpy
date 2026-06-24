"""
Machine-readable integration manifest.

Exposes public, non-sensitive metadata about this SpeedPy installation so
agents, CLIs, MCP servers, and automation clients can discover capabilities
without scraping docs or README text.

Served at both ``/.well-known/speedpy.json`` and ``/api/v1/health/manifest/``.
"""

from django.conf import settings
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from mainapp.webhooks.events import WebhookEvent


def _base_url(request):
    """Return the canonical base URL for this installation."""
    if settings.SITE_URL:
        return settings.SITE_URL.rstrip("/")
    return request.build_absolute_uri("/").rstrip("/")


def _build_manifest(request):
    base = _base_url(request)
    teams_enabled = getattr(settings, "SPEEDPY_TEAMS_ENABLED", True)
    dcr_enabled = getattr(settings, "DCR_ENABLED", False)
    api_docs_public = getattr(settings, "API_DOCS_PUBLIC", False)
    scopes = getattr(settings, "OAUTH2_PROVIDER", {}).get("SCOPES", {})
    api_version = getattr(settings, "SPECTACULAR_SETTINGS", {}).get("VERSION", "1.0.0")

    return {
        "manifest_version": "1.0",
        "service": {
            "name": "SpeedPy",
            "title": getattr(settings, "TITLE", "SpeedPy"),
            "tagline": getattr(settings, "TAGLINE", ""),
            "api_version": api_version,
            "base_url": base,
        },
        "links": {
            "openapi_schema": f"{base}/api/schema/",
            "swagger_ui": f"{base}/api/docs/",
            "redoc": f"{base}/api/redoc/",
            "agents_md": "AGENTS.md",
        },
        "auth": {
            "session": {
                "type": "cookie",
                "cookie_name": "sessionid",
                "login_url": f"{base}/accounts/login/",
            },
            "personal_access_token": {
                "type": "bearer",
                "prefix": "spd_",
                "management_url": f"{base}/accounts/tokens/",
            },
            "jwt": {
                "type": "bearer",
                "obtain_url": f"{base}/api/auth/token/",
                "refresh_url": f"{base}/api/auth/token/refresh/",
                "revoke_url": f"{base}/api/auth/token/revoke/",
            },
            "oauth2": {
                "type": "oauth2",
                "authorization_url": f"{base}/o/authorize/",
                "token_url": f"{base}/o/token/",
                "device_authorization_url": f"{base}/o/device-authorization/",
                "grants": ["authorization_code_pkce", "device_code"],
            },
            "dynamic_client_registration": {
                "url": f"{base}/o/register/",
                "enabled": dcr_enabled,
            },
        },
        "scopes": {
            name: description for name, description in scopes.items()
        },
        "endpoints": {
            "current_user": {
                "url": f"{base}/api/v1/me/",
                "methods": ["GET", "PATCH"],
            },
            "teams": {
                "list_url": f"{base}/api/v1/teams/",
                "detail_url": f"{base}/api/v1/teams/{{team_id}}/",
                "members_url": f"{base}/api/v1/teams/{{team_id}}/members/",
                "invitations_url": f"{base}/api/v1/teams/{{team_id}}/invitations/",
                "enabled": teams_enabled,
            },
            "webhooks": {
                "user_list_url": f"{base}/api/v1/webhooks/",
                "team_list_url": f"{base}/api/v1/teams/{{team_id}}/webhooks/",
            },
        },
        "capabilities": {
            "teams_enabled": teams_enabled,
            "webhooks_enabled": True,
            "api_docs_public": api_docs_public,
            "webhook_events": sorted(WebhookEvent.ALL),
        },
        "examples": {
            "readme": "examples/README.md",
            "cli": "examples/cli/speedpy_cli.py",
            "mcp_server": "examples/mcp_server/speedpy_mcp.py",
        },
    }


class IntegrationManifestView(APIView):
    """Public, unauthenticated integration manifest."""

    authentication_classes = []
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    @extend_schema(
        tags=["integration"],
        operation_id="getIntegrationManifest",
        summary="Machine-readable integration manifest",
        description=(
            "Returns public metadata about this SpeedPy installation: "
            "API schema URL, auth methods, scopes, endpoints, and capabilities. "
            "No authentication required. Agents, CLIs, and MCP servers should use "
            "this endpoint to discover available features and URLs."
        ),
        responses={200: dict},
        examples=[
            OpenApiExample(
                "Manifest",
                value={
                    "manifest_version": "1.0",
                    "service": {
                        "name": "SpeedPy",
                        "title": "SpeedPy",
                        "tagline": "",
                        "api_version": "1.0.0",
                        "base_url": "https://app.example.com",
                    },
                    "links": {
                        "openapi_schema": "https://app.example.com/api/schema/",
                        "swagger_ui": "https://app.example.com/api/docs/",
                        "redoc": "https://app.example.com/api/redoc/",
                        "agents_md": "AGENTS.md",
                    },
                    "auth": {
                        "session": {"type": "cookie", "cookie_name": "sessionid"},
                        "personal_access_token": {"type": "bearer", "prefix": "spd_"},
                        "jwt": {"type": "bearer", "obtain_url": "https://app.example.com/api/auth/token/"},
                        "oauth2": {"type": "oauth2", "authorization_url": "https://app.example.com/o/authorize/"},
                    },
                    "capabilities": {
                        "teams_enabled": True,
                        "webhooks_enabled": True,
                        "webhook_events": ["team.invitation.created", "team.member.added", "user.profile.updated"],
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request):
        return Response(_build_manifest(request))


class WellKnownManifestView(APIView):
    """/.well-known/speedpy.json — same payload, excluded from OpenAPI schema."""

    authentication_classes = []
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    @extend_schema(exclude=True)
    def get(self, request):
        return Response(_build_manifest(request))
