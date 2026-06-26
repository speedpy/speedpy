"""
Webhook management API — CRUD, rotate-secret, test delivery, and delivery retry.

Team-scoped endpoints live under ``/api/v1/teams/{team_id}/webhooks/``.
A user-scoped read-only list lives at ``/api/v1/webhooks/``.
"""

import time
import uuid

import structlog
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from mainapp.models import Team, TeamMembership
from mainapp.models.webhooks import WebhookDelivery, WebhookEndpoint
from mainapp.webhooks.events import WebhookEvent
from speedpycom.api.permissions import HasScope

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_membership(user, team_id):
    """Get the user's active membership for a team, or raise 404."""
    try:
        membership = TeamMembership.objects.select_related("team").get(
            team_id=team_id,
            user=user,
            team__is_active=True,
        )
    except TeamMembership.DoesNotExist:
        raise NotFound()
    if membership.access_expires_at and membership.access_expires_at <= timezone.now():
        raise NotFound()
    return membership


def _require_write_role(membership):
    """Raise 403 if the member's role does not allow writes."""
    if membership.role not in ("owner", "admin", "member"):
        raise PermissionDenied("Your role does not allow managing webhooks.")


def _get_endpoint(team, webhook_id):
    """Retrieve a webhook endpoint belonging to a team, or 404."""
    try:
        return WebhookEndpoint.objects.get(id=webhook_id, team=team)
    except WebhookEndpoint.DoesNotExist:
        raise NotFound()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class WebhookEndpointListSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    url = serializers.URLField(read_only=True)
    events = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class WebhookEndpointCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, default="")
    url = serializers.URLField(max_length=2048)
    events = serializers.ListField(child=serializers.CharField(), min_length=1)

    def validate_url(self, value):
        if not value.startswith("https://"):
            raise serializers.ValidationError("Only HTTPS URLs are allowed.")
        return value

    def validate_events(self, value):
        for event in value:
            if event != "*" and event not in WebhookEvent.ALL:
                raise serializers.ValidationError(
                    f"Unknown event type: {event}"
                )
        return value


class WebhookEndpointUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    url = serializers.URLField(max_length=2048, required=False)
    events = serializers.ListField(child=serializers.CharField(), min_length=1, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_url(self, value):
        if not value.startswith("https://"):
            raise serializers.ValidationError("Only HTTPS URLs are allowed.")
        return value

    def validate_events(self, value):
        for event in value:
            if event != "*" and event not in WebhookEvent.ALL:
                raise serializers.ValidationError(
                    f"Unknown event type: {event}"
                )
        return value


class WebhookEndpointCreateResponseSerializer(WebhookEndpointListSerializer):
    signing_secret = serializers.CharField(read_only=True)


class WebhookEndpointRotateResponseSerializer(WebhookEndpointListSerializer):
    signing_secret = serializers.CharField(read_only=True)
    secret_rotated_at = serializers.DateTimeField(read_only=True)
    previous_secret_expires_at = serializers.DateTimeField(read_only=True)
    rotation_overlap_seconds = serializers.IntegerField(read_only=True)


class WebhookDeliveryListSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    event_id = serializers.CharField(read_only=True)
    event_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    http_status_code = serializers.IntegerField(read_only=True, allow_null=True)
    attempts = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    delivered_at = serializers.DateTimeField(read_only=True, allow_null=True)
    error_message = serializers.CharField(read_only=True)


class WebhookDeliveryDetailSerializer(WebhookDeliveryListSerializer):
    payload = serializers.JSONField(read_only=True)
    response_body = serializers.CharField(read_only=True)


class WebhookTestDeliverySerializer(serializers.Serializer):
    event_type = serializers.CharField(required=False)


# ---------------------------------------------------------------------------
# Views — Team-scoped
# ---------------------------------------------------------------------------

class TeamWebhookEndpointListCreateView(APIView):
    """List and create webhook endpoints for a team."""

    permission_classes = [HasScope]
    required_scopes = ["read:webhooks"]

    @extend_schema(
        tags=["webhooks"],
        operation_id="listTeamWebhookEndpoints",
        summary="List webhook endpoints for a team",
        description=(
            "Return a paginated list of webhook endpoints belonging to the team. "
            "Requires team membership and the `read:webhooks` scope."
        ),
        responses={
            200: WebhookEndpointListSerializer(many=True),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
        examples=[
            OpenApiExample(
                "Webhook endpoint list",
                value={
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": "f1e2d3c4-b5a6-7890-fedc-ba0987654321",
                            "name": "Production",
                            "url": "https://hooks.example.com/speedpy",
                            "events": ["*"],
                            "is_active": True,
                            "created_at": "2025-05-01T08:00:00Z",
                            "updated_at": "2025-06-10T12:30:00Z",
                        }
                    ],
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, team_id):
        membership = _get_membership(request.user, team_id)
        endpoints = WebhookEndpoint.objects.filter(team=membership.team).order_by("-created_at")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(endpoints, request)
        data = WebhookEndpointListSerializer(page, many=True).data
        return paginator.get_paginated_response(data)

    @extend_schema(
        tags=["webhooks"],
        operation_id="createTeamWebhookEndpoint",
        summary="Create a webhook endpoint",
        description=(
            "Register a new webhook endpoint for the team. The URL must use HTTPS. "
            "Pass `[\"*\"]` as events to subscribe to all event types, or list specific types "
            "(e.g. `[\"team.member.added\", \"user.profile.updated\"]`). "
            "The response includes a one-time `signing_secret` used to verify delivery signatures. "
            "Requires an owner, admin, or member role and the `write:webhooks` scope."
        ),
        request=WebhookEndpointCreateSerializer,
        responses={
            201: WebhookEndpointCreateResponseSerializer,
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
        examples=[
            OpenApiExample(
                "Create endpoint",
                value={
                    "name": "Production",
                    "url": "https://hooks.example.com/speedpy",
                    "events": ["*"],
                },
                request_only=True,
            ),
            OpenApiExample(
                "Endpoint created",
                value={
                    "id": "f1e2d3c4-b5a6-7890-fedc-ba0987654321",
                    "name": "Production",
                    "url": "https://hooks.example.com/speedpy",
                    "events": ["*"],
                    "is_active": True,
                    "created_at": "2025-05-01T08:00:00Z",
                    "updated_at": "2025-05-01T08:00:00Z",
                    "signing_secret": "whsec_abc123def456...",
                },
                response_only=True,
                status_codes=["201"],
            ),
        ],
    )
    def post(self, request, team_id):
        self.required_scopes = ["write:webhooks"]
        membership = _get_membership(request.user, team_id)
        _require_write_role(membership)

        serializer = WebhookEndpointCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        endpoint = WebhookEndpoint(
            team=membership.team,
            name=serializer.validated_data.get("name", ""),
            url=serializer.validated_data["url"],
            events=serializer.validated_data["events"],
        )
        endpoint.save()

        response_data = WebhookEndpointListSerializer(endpoint).data
        response_data["signing_secret"] = endpoint.secret

        logger.info(
            "api_webhook_endpoint_created",
            user_id=str(request.user.id),
            team_id=str(team_id),
            endpoint_id=str(endpoint.id),
        )

        return Response(response_data, status=status.HTTP_201_CREATED)

    def check_permissions(self, request):
        if request.method == "POST":
            self.required_scopes = ["write:webhooks"]
        else:
            self.required_scopes = ["read:webhooks"]
        super().check_permissions(request)


class TeamWebhookEndpointDetailView(APIView):
    """Retrieve, update, or soft-delete a webhook endpoint."""

    permission_classes = [HasScope]
    required_scopes = ["read:webhooks"]

    def check_permissions(self, request):
        if request.method in ("PUT", "PATCH", "DELETE"):
            self.required_scopes = ["write:webhooks"]
        else:
            self.required_scopes = ["read:webhooks"]
        super().check_permissions(request)

    @extend_schema(
        tags=["webhooks"],
        operation_id="getTeamWebhookEndpoint",
        summary="Get a webhook endpoint",
        description="Return a single webhook endpoint by ID. Requires team membership and the `read:webhooks` scope.",
        responses={
            200: WebhookEndpointListSerializer,
            404: OpenApiResponse(description="Not found."),
        },
    )
    def get(self, request, team_id, webhook_id):
        membership = _get_membership(request.user, team_id)
        endpoint = _get_endpoint(membership.team, webhook_id)
        return Response(WebhookEndpointListSerializer(endpoint).data)

    @extend_schema(
        tags=["webhooks"],
        operation_id="updateTeamWebhookEndpoint",
        summary="Update a webhook endpoint",
        description="Replace all mutable fields of a webhook endpoint. Requires the `write:webhooks` scope.",
        request=WebhookEndpointUpdateSerializer,
        responses={
            200: WebhookEndpointListSerializer,
            400: OpenApiResponse(description="Validation error."),
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Not found."),
        },
    )
    def put(self, request, team_id, webhook_id):
        return self._update(request, team_id, webhook_id)

    @extend_schema(
        tags=["webhooks"],
        operation_id="patchTeamWebhookEndpoint",
        summary="Partially update a webhook endpoint",
        description="Update one or more fields of a webhook endpoint. Requires the `write:webhooks` scope.",
        request=WebhookEndpointUpdateSerializer,
        responses={
            200: WebhookEndpointListSerializer,
            400: OpenApiResponse(description="Validation error."),
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Not found."),
        },
    )
    def patch(self, request, team_id, webhook_id):
        return self._update(request, team_id, webhook_id)

    def _update(self, request, team_id, webhook_id):
        membership = _get_membership(request.user, team_id)
        _require_write_role(membership)
        endpoint = _get_endpoint(membership.team, webhook_id)

        serializer = WebhookEndpointUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        for field, value in serializer.validated_data.items():
            setattr(endpoint, field, value)
        endpoint.save()

        logger.info(
            "api_webhook_endpoint_updated",
            user_id=str(request.user.id),
            team_id=str(team_id),
            endpoint_id=str(endpoint.id),
        )

        return Response(WebhookEndpointListSerializer(endpoint).data)

    @extend_schema(
        tags=["webhooks"],
        operation_id="deleteTeamWebhookEndpoint",
        summary="Soft-delete a webhook endpoint",
        description=(
            "Deactivate a webhook endpoint and clear its event subscriptions. "
            "The endpoint record is kept for audit purposes. Requires the `write:webhooks` scope."
        ),
        responses={
            204: OpenApiResponse(description="Endpoint deactivated."),
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Not found."),
        },
    )
    def delete(self, request, team_id, webhook_id):
        membership = _get_membership(request.user, team_id)
        _require_write_role(membership)
        endpoint = _get_endpoint(membership.team, webhook_id)

        endpoint.is_active = False
        endpoint.events = []
        endpoint.save(update_fields=["is_active", "events", "updated_at"])

        logger.info(
            "api_webhook_endpoint_soft_deleted",
            user_id=str(request.user.id),
            team_id=str(team_id),
            endpoint_id=str(endpoint.id),
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamWebhookEndpointRotateSecretView(APIView):
    """Rotate the signing secret for a webhook endpoint."""

    permission_classes = [HasScope]
    required_scopes = ["write:webhooks"]

    @extend_schema(
        tags=["webhooks"],
        operation_id="rotateTeamWebhookEndpointSecret",
        summary="Rotate a webhook endpoint's signing secret",
        description=(
            "Generate a new signing secret for the endpoint. The previous secret remains "
            "accepted by verifiers during a configurable overlap window (default 24 hours). "
            "The new secret is returned once in the response. "
            "Requires the `write:webhooks` scope."
        ),
        request=None,
        responses={
            200: WebhookEndpointRotateResponseSerializer,
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Not found."),
        },
    )
    def post(self, request, team_id, webhook_id):
        membership = _get_membership(request.user, team_id)
        _require_write_role(membership)
        endpoint = _get_endpoint(membership.team, webhook_id)

        endpoint.rotate_secret()

        response_data = WebhookEndpointListSerializer(endpoint).data
        response_data["signing_secret"] = endpoint.secret
        response_data["secret_rotated_at"] = endpoint.secret_rotated_at.isoformat()
        response_data["previous_secret_expires_at"] = endpoint.previous_secret_expires_at.isoformat()
        response_data["rotation_overlap_seconds"] = endpoint.get_rotation_overlap_seconds()

        logger.info(
            "api_webhook_endpoint_secret_rotated",
            user_id=str(request.user.id),
            team_id=str(team_id),
            endpoint_id=str(endpoint.id),
        )

        return Response(response_data)


class TeamWebhookEndpointTestView(APIView):
    """Dispatch a synthetic test event to a webhook endpoint."""

    permission_classes = [HasScope]
    required_scopes = ["write:webhooks"]

    @extend_schema(
        tags=["webhooks"],
        operation_id="testTeamWebhookEndpoint",
        summary="Send a test delivery to a webhook endpoint",
        description=(
            "Dispatch a synthetic test event to the endpoint's URL. "
            "If `event_type` is omitted, the first subscribed event type is used "
            "(or `team.member.added` when subscribed to `*`). "
            "The endpoint must be active. Requires the `write:webhooks` scope."
        ),
        request=WebhookTestDeliverySerializer,
        responses={
            201: WebhookDeliveryDetailSerializer,
            400: OpenApiResponse(description="Endpoint inactive or invalid event type."),
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Not found."),
        },
        examples=[
            OpenApiExample(
                "Test delivery request",
                value={"event_type": "team.member.added"},
                request_only=True,
            ),
        ],
    )
    def post(self, request, team_id, webhook_id):
        membership = _get_membership(request.user, team_id)
        _require_write_role(membership)
        endpoint = _get_endpoint(membership.team, webhook_id)

        if not endpoint.is_active:
            return Response(
                {"detail": "Cannot send test delivery to an inactive endpoint."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = WebhookTestDeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_type = serializer.validated_data.get("event_type")
        if not event_type:
            if not endpoint.events:
                return Response(
                    {"detail": "Endpoint has no subscribed events."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            event_type = endpoint.events[0] if endpoint.events[0] != "*" else "team.member.added"

        if event_type not in WebhookEvent.ALL:
            return Response(
                {"detail": f"Unknown event type: {event_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not endpoint.subscribes_to(event_type):
            return Response(
                {"detail": f"Event type '{event_type}' is not in this endpoint's subscription."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from mainapp.tasks.webhooks import deliver_webhook

        event_id = f"evt_{uuid.uuid4().hex}"
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": int(time.time()),
            "api_version": "2026-06-01",
            "data": {
                "test": True,
                "endpoint_id": str(endpoint.id),
                "triggered_by": str(request.user.id),
            },
        }

        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        transaction.on_commit(lambda pk=delivery.pk: deliver_webhook.delay(pk))

        logger.info(
            "api_webhook_test_delivery_created",
            user_id=str(request.user.id),
            team_id=str(team_id),
            endpoint_id=str(endpoint.id),
            delivery_id=delivery.pk,
        )

        return Response(
            WebhookDeliveryDetailSerializer(delivery).data,
            status=status.HTTP_201_CREATED,
        )


class TeamWebhookDeliveryListView(ListAPIView):
    """List deliveries for a webhook endpoint."""

    serializer_class = WebhookDeliveryListSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:webhooks"]

    def get_queryset(self):
        membership = _get_membership(self.request.user, self.kwargs["team_id"])
        endpoint = _get_endpoint(membership.team, self.kwargs["webhook_id"])
        return WebhookDelivery.objects.filter(endpoint=endpoint).order_by("-created_at")

    @extend_schema(
        tags=["webhooks"],
        operation_id="listTeamWebhookDeliveries",
        summary="List deliveries for a webhook endpoint",
        description=(
            "Return a paginated list of delivery attempts for the specified webhook endpoint, "
            "ordered by most recent first. Requires the `read:webhooks` scope."
        ),
        responses={
            200: WebhookDeliveryListSerializer(many=True),
            404: OpenApiResponse(description="Not found."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TeamWebhookDeliveryDetailView(APIView):
    """Get details of a specific delivery."""

    permission_classes = [HasScope]
    required_scopes = ["read:webhooks"]

    @extend_schema(
        tags=["webhooks"],
        operation_id="getTeamWebhookDelivery",
        summary="Get a webhook delivery",
        description=(
            "Return full details of a delivery attempt, including the request payload "
            "and response body. Requires the `read:webhooks` scope."
        ),
        responses={
            200: WebhookDeliveryDetailSerializer,
            404: OpenApiResponse(description="Not found."),
        },
    )
    def get(self, request, team_id, webhook_id, delivery_id):
        membership = _get_membership(request.user, team_id)
        endpoint = _get_endpoint(membership.team, webhook_id)
        try:
            delivery = WebhookDelivery.objects.get(pk=delivery_id, endpoint=endpoint)
        except WebhookDelivery.DoesNotExist:
            raise NotFound()
        return Response(WebhookDeliveryDetailSerializer(delivery).data)


class TeamWebhookDeliveryRetryView(APIView):
    """Retry a failed delivery."""

    permission_classes = [HasScope]
    required_scopes = ["write:webhooks"]

    @extend_schema(
        tags=["webhooks"],
        operation_id="retryTeamWebhookDelivery",
        summary="Retry a failed webhook delivery",
        description=(
            "Reset a failed delivery to PENDING and re-dispatch it. "
            "Only deliveries with status `FAILED` can be retried. "
            "Requires the `write:webhooks` scope."
        ),
        request=None,
        responses={
            200: WebhookDeliveryDetailSerializer,
            400: OpenApiResponse(description="Delivery is not in FAILED status."),
            403: OpenApiResponse(description="Insufficient role."),
            404: OpenApiResponse(description="Not found."),
        },
    )
    def post(self, request, team_id, webhook_id, delivery_id):
        membership = _get_membership(request.user, team_id)
        _require_write_role(membership)
        endpoint = _get_endpoint(membership.team, webhook_id)

        try:
            delivery = WebhookDelivery.objects.get(pk=delivery_id, endpoint=endpoint)
        except WebhookDelivery.DoesNotExist:
            raise NotFound()

        if delivery.status != WebhookDelivery.Status.FAILED:
            return Response(
                {"detail": f"Only failed deliveries can be retried. Current status: {delivery.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from mainapp.tasks.webhooks import deliver_webhook

        delivery.status = WebhookDelivery.Status.PENDING
        delivery.attempts = 0
        delivery.error_message = ""
        delivery.save(update_fields=["status", "attempts", "error_message", "updated_at"])

        transaction.on_commit(lambda pk=delivery.pk: deliver_webhook.delay(pk))

        logger.info(
            "api_webhook_delivery_retried",
            user_id=str(request.user.id),
            team_id=str(team_id),
            endpoint_id=str(endpoint.id),
            delivery_id=delivery.pk,
        )

        return Response(WebhookDeliveryDetailSerializer(delivery).data)


# ---------------------------------------------------------------------------
# Views — User-scoped
# ---------------------------------------------------------------------------

class UserWebhookEndpointListView(ListAPIView):
    """List all webhook endpoints across the user's teams (read-only)."""

    serializer_class = WebhookEndpointListSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:webhooks"]

    def get_queryset(self):
        now = timezone.now()
        team_ids = TeamMembership.objects.filter(
            user=self.request.user,
            team__is_active=True,
        ).exclude(
            access_expires_at__lte=now,
        ).values_list("team_id", flat=True)
        return WebhookEndpoint.objects.filter(team_id__in=team_ids).order_by("-created_at")

    @extend_schema(
        tags=["webhooks"],
        operation_id="listUserWebhookEndpoints",
        summary="List webhook endpoints across all user's teams",
        description=(
            "Return a combined list of webhook endpoints from every active team the "
            "authenticated user belongs to. Read-only. Requires the `read:webhooks` scope."
        ),
        responses={
            200: WebhookEndpointListSerializer(many=True),
            401: OpenApiResponse(description="Authentication required."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
