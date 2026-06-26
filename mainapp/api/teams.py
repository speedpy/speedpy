"""
Team-scoped API — canonical reference for tenant-isolated endpoints.

Copy this pattern when adding API endpoints for team-owned resources.
"""

from functools import partial

import structlog
from celery import current_app
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from mainapp.models import Team, TeamInvitation, TeamMembership
from speedpycom.api.idempotency import idempotent
from speedpycom.api.permissions import HasScope

User = get_user_model()

logger = structlog.get_logger(__name__)


def _check_teams_enabled():
    """Raise 404 if teams feature is disabled."""
    if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
        raise NotFound()


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


# --- Serializers ---


class TeamSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    plan = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class TeamDetailSerializer(TeamSerializer):
    member_count = serializers.SerializerMethodField()

    def get_member_count(self, team) -> int:
        return team.teammembership_set.count()


class TeamMemberSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    role = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class CreateInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=[("admin", "Admin"), ("member", "Member"), ("viewer", "Viewer")]
    )
    message = serializers.CharField(required=False, allow_blank=True, default="")


class InvitationResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    role = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)


# --- Views ---


class TeamListAPIView(ListAPIView):
    """List teams the authenticated user belongs to."""

    serializer_class = TeamSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:teams"]

    def get_queryset(self):
        _check_teams_enabled()
        now = timezone.now()
        return Team.objects.filter(
            teammembership__user=self.request.user,
            teammembership__team__is_active=True,
        ).exclude(
            teammembership__access_expires_at__lte=now,
        ).distinct().order_by("name")

    @extend_schema(
        tags=["teams"],
        operation_id="listTeams",
        summary="List teams for the authenticated user",
        description=(
            "Return all active teams the authenticated user is a member of. "
            "Expired memberships are excluded. Requires the `read:teams` scope. "
            "Returns 404 if the teams feature is disabled."
        ),
        responses={
            200: TeamSerializer(many=True),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Teams feature is disabled."),
        },
        examples=[
            OpenApiExample(
                "Team list",
                value=[
                    {
                        "id": "c1d2e3f4-a5b6-7890-cdef-123456789abc",
                        "name": "Acme Corp",
                        "slug": "acme-corp",
                        "plan": "pro",
                        "is_active": True,
                        "created_at": "2025-03-01T10:00:00Z",
                        "updated_at": "2025-06-15T14:30:00Z",
                    }
                ],
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TeamDetailAPIView(RetrieveAPIView):
    """Get a team by ID (membership required)."""

    serializer_class = TeamDetailSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:teams"]

    def get_object(self):
        _check_teams_enabled()
        membership = _get_membership(self.request.user, self.kwargs["team_id"])
        return membership.team

    @extend_schema(
        tags=["teams"],
        operation_id="getTeam",
        summary="Get a team",
        description=(
            "Return details of a single team including its member count. "
            "The caller must be an active member of the team. Requires the `read:teams` scope."
        ),
        responses={
            200: TeamDetailSerializer,
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
        examples=[
            OpenApiExample(
                "Team detail",
                value={
                    "id": "c1d2e3f4-a5b6-7890-cdef-123456789abc",
                    "name": "Acme Corp",
                    "slug": "acme-corp",
                    "plan": "pro",
                    "is_active": True,
                    "created_at": "2025-03-01T10:00:00Z",
                    "updated_at": "2025-06-15T14:30:00Z",
                    "member_count": 5,
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TeamMembersAPIView(ListAPIView):
    """List members of a team (membership required)."""

    serializer_class = TeamMemberSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:teams"]

    def get_queryset(self):
        _check_teams_enabled()
        membership = _get_membership(self.request.user, self.kwargs["team_id"])
        return TeamMembership.objects.filter(
            team=membership.team,
        ).select_related("user").order_by("role", "created_at")

    @extend_schema(
        tags=["teams"],
        operation_id="listTeamMembers",
        summary="List team members",
        description=(
            "Return all members of the specified team, ordered by role then join date. "
            "The caller must be an active member. Requires the `read:teams` scope."
        ),
        responses={
            200: TeamMemberSerializer(many=True),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
        examples=[
            OpenApiExample(
                "Member list",
                value=[
                    {
                        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                        "email": "jane@example.com",
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "role": "owner",
                        "created_at": "2025-03-01T10:00:00Z",
                    }
                ],
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TeamInvitationCreateAPIView(APIView):
    """Create an invitation to a team (owner/admin only)."""

    permission_classes = [HasScope]
    required_scopes = ["write:teams"]

    @extend_schema(
        tags=["teams"],
        request=CreateInvitationSerializer,
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=str,
                location=OpenApiParameter.HEADER,
                required=False,
                description="Optional idempotency key (1-128 chars). Same key + same body replays the stored response.",
            ),
        ],
        responses={
            201: InvitationResponseSerializer,
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(description="Insufficient role (owner/admin required)."),
            404: OpenApiResponse(description="Team not found or no access."),
            409: OpenApiResponse(description="Idempotency-Key reused with a different request body."),
        },
        operation_id="createTeamInvitation",
        summary="Invite a user to a team",
        description=(
            "Send an invitation email to a user. Only owners and admins can create invitations, "
            "and the caller's role must be sufficient to assign the requested target role. "
            "Supports idempotent creation via the `Idempotency-Key` header. "
            "Requires the `write:teams` scope."
        ),
        examples=[
            OpenApiExample(
                "Invite a member",
                value={"email": "bob@example.com", "role": "member", "message": "Welcome to the team!"},
                request_only=True,
            ),
            OpenApiExample(
                "Invitation created",
                value={
                    "id": "d4e5f6a7-b8c9-0123-def4-567890abcdef",
                    "email": "bob@example.com",
                    "role": "member",
                    "status": "pending",
                    "created_at": "2025-06-20T12:00:00Z",
                    "expires_at": "2025-07-04T12:00:00Z",
                },
                response_only=True,
                status_codes=["201"],
            ),
        ],
    )
    @idempotent
    def post(self, request, team_id):
        _check_teams_enabled()
        membership = _get_membership(request.user, team_id)

        if membership.role not in ("owner", "admin"):
            raise PermissionDenied("Only owners and admins can invite members.")

        serializer = CreateInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_role = serializer.validated_data["role"]
        if not membership.can_invite_role(target_role):
            raise PermissionDenied(
                f"Your role ({membership.role}) cannot invite {target_role}s."
            )

        email = serializer.validated_data["email"]
        user = User.objects.filter(email=email).first()

        invitation = TeamInvitation.objects.create(
            team=membership.team,
            invited_by=request.user,
            email=email,
            user=user,
            role=target_role,
            message=serializer.validated_data.get("message", ""),
        )
        transaction.on_commit(
            partial(
                current_app.send_task,
                "send_team_invitation_email",
                kwargs={"invitation_id": invitation.pk},
            )
        )

        logger.info(
            "api_team_invitation_created",
            user_id=str(request.user.id),
            team_id=str(team_id),
            invitation_id=str(invitation.id),
            invited_email=invitation.email,
            role=target_role,
        )

        return Response(
            InvitationResponseSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )
