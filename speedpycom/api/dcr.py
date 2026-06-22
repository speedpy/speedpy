import time

import structlog
from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from oauth2_provider.models import get_application_model
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = structlog.get_logger(__name__)

Application = get_application_model()

# Mapping from RFC 7591 grant_types to DOT authorization_grant_type values.
_GRANT_TYPE_MAP = {
    "authorization_code": Application.GRANT_AUTHORIZATION_CODE,
    "urn:ietf:params:oauth:grant-type:device_code": "urn:ietf:params:oauth:grant-type:device_code",
}


class DynamicClientRegistrationView(APIView):
    """RFC 7591 Dynamic Client Registration endpoint."""

    permission_classes = [AllowAny]
    authentication_classes = []  # No authentication required

    @extend_schema(
        tags=["oauth2"],
        operation_id="dcr_register",
        summary="Register an OAuth2 client (RFC 7591)",
        request=inline_serializer(
            name="DCRRequest",
            fields={
                "client_name": serializers.CharField(help_text="Human-readable client name."),
                "grant_types": serializers.ListField(
                    child=serializers.CharField(),
                    required=False,
                    help_text="OAuth2 grant types the client will use.",
                ),
                "scope": serializers.CharField(required=False, help_text="Space-separated scopes."),
                "token_endpoint_auth_method": serializers.CharField(
                    required=False,
                    help_text="Token endpoint authentication method. Use 'none' for public clients.",
                ),
                "redirect_uris": serializers.ListField(
                    child=serializers.URLField(),
                    required=False,
                    help_text="Redirect URIs for authorization code flow.",
                ),
            },
        ),
        responses={
            201: inline_serializer(
                name="DCRResponse",
                fields={
                    "client_id": serializers.CharField(),
                    "client_secret": serializers.CharField(required=False),
                    "client_name": serializers.CharField(),
                    "grant_types": serializers.ListField(child=serializers.CharField()),
                    "scope": serializers.CharField(),
                    "token_endpoint_auth_method": serializers.CharField(),
                    "client_id_issued_at": serializers.IntegerField(),
                },
            ),
            400: inline_serializer(
                name="DCRError",
                fields={
                    "error": serializers.CharField(),
                    "error_description": serializers.CharField(),
                },
            ),
        },
    )
    def post(self, request):
        if not settings.DCR_ENABLED:
            return Response(status=status.HTTP_404_NOT_FOUND)

        data = request.data

        client_name = data.get("client_name")
        if not client_name:
            return Response(
                {
                    "error": "invalid_client_metadata",
                    "error_description": "client_name is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        grant_types = data.get("grant_types", ["authorization_code"])
        scope = data.get("scope", "")
        auth_method = data.get("token_endpoint_auth_method", "client_secret_basic")
        redirect_uris = data.get("redirect_uris", [])

        # Map the first grant type to DOT's authorization_grant_type.
        if not grant_types:
            grant_types = ["authorization_code"]
        primary_grant = grant_types[0]
        dot_grant_type = _GRANT_TYPE_MAP.get(primary_grant)
        if dot_grant_type is None:
            return Response(
                {
                    "error": "invalid_client_metadata",
                    "error_description": f"Unsupported grant type: {primary_grant}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine client type from auth method.
        if auth_method == "none":
            client_type = Application.CLIENT_PUBLIC
        else:
            client_type = Application.CLIENT_CONFIDENTIAL

        app = Application(
            name=client_name,
            authorization_grant_type=dot_grant_type,
            client_type=client_type,
            redirect_uris=" ".join(redirect_uris),
        )
        app.save()

        logger.info(
            "dcr_client_registered",
            client_id=app.client_id,
            client_name=client_name,
            grant_type=dot_grant_type,
            client_type=client_type,
        )

        response_data = {
            "client_id": app.client_id,
            "client_name": client_name,
            "grant_types": grant_types,
            "scope": scope,
            "token_endpoint_auth_method": auth_method,
            "client_id_issued_at": int(time.time()),
        }

        if client_type == Application.CLIENT_CONFIDENTIAL:
            response_data["client_secret"] = app.client_secret

        return Response(response_data, status=status.HTTP_201_CREATED)
