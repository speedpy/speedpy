"""
Team-scoped API — canonical reference for tenant-isolated endpoints.

Copy this pattern when adding API endpoints for team-owned resources.
"""

import structlog
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from mainapp.models import Team, TeamInvitation, TeamMembership
from speedpycom.api.permissions import HasScope

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
        responses={
            200: TeamSerializer(many=True),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Teams feature is disabled."),
        },
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
        responses={
            200: TeamDetailSerializer,
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
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
        responses={
            200: TeamMemberSerializer(many=True),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
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
        responses={
            201: InvitationResponseSerializer,
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(description="Insufficient role (owner/admin required)."),
            404: OpenApiResponse(description="Team not found or no access."),
        },
        operation_id="createTeamInvitation",
        summary="Invite a user to a team",
    )
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

        invitation = TeamInvitation.objects.create(
            team=membership.team,
            invited_by=request.user,
            email=serializer.validated_data["email"],
            role=target_role,
            message=serializer.validated_data.get("message", ""),
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
