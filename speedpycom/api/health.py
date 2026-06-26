"""
Integration health-check endpoint.

Lightweight, unauthenticated endpoint for uptime monitors and MCP
connectivity checks.  Returns API version, response-schema version,
feature flags, and a fixed ``"ok"`` status.  No database queries, no
sensitive data.

Served at ``/api/v1/health/`` and ``/health/``.
"""

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView


def _build_health(request):
    api_version = getattr(settings, "SPECTACULAR_SETTINGS", {}).get(
        "VERSION", "1.0.0"
    )
    teams_enabled = getattr(settings, "SPEEDPY_TEAMS_ENABLED", True)

    return {
        "status": "ok",
        "api_version": api_version,
        "schema_version": "1.0",
        "timestamp": timezone.now().isoformat(),
        "features": {
            "teams_enabled": teams_enabled,
        },
    }


class _HealthFeaturesSerializer(serializers.Serializer):
    teams_enabled = serializers.BooleanField()


class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    api_version = serializers.CharField()
    schema_version = serializers.CharField()
    timestamp = serializers.DateTimeField()
    features = _HealthFeaturesSerializer()


_HEALTH_EXAMPLE = {
    "status": "ok",
    "api_version": "1.0.0",
    "schema_version": "1.0",
    "timestamp": "2026-06-26T12:00:00+00:00",
    "features": {
        "teams_enabled": True,
    },
}


class HealthCheckView(APIView):
    """Public, unauthenticated health check for monitors and MCP clients."""

    authentication_classes = []
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    @extend_schema(
        tags=["integration"],
        operation_id="getHealthCheck",
        summary="Integration health check",
        description=(
            "Returns a lightweight health payload with API version, "
            "response-schema version, feature flags, and current timestamp. "
            "No authentication required.  Designed for uptime monitors and "
            "MCP connectivity checks.  Does not query the database."
        ),
        responses={200: HealthCheckSerializer},
        examples=[
            OpenApiExample(
                "Health",
                value=_HEALTH_EXAMPLE,
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request):
        return Response(_build_health(request))


class RootHealthCheckView(APIView):
    """/health/ — same payload, excluded from OpenAPI schema."""

    authentication_classes = []
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    @extend_schema(exclude=True)
    def get(self, request):
        return Response(_build_health(request))
