"""
Production dispatch helpers for v1 webhook events.

Each helper constructs a tenant-safe payload and calls ``dispatch_event()``.
Signal receivers and views call these instead of ``dispatch_event()`` directly,
so payload shape is defined in one place and tests can assert against a stable API.
"""

from django.utils import timezone

from mainapp.webhooks.dispatch import dispatch_event
from mainapp.webhooks.events import WebhookEvent


def on_team_member_added(membership):
    """Dispatch ``team.member.added`` for a newly created TeamMembership."""
    dispatch_event(
        team=membership.team,
        event_type=WebhookEvent.TEAM_MEMBER_ADDED,
        data={
            "team_id": str(membership.team_id),
            "membership_id": str(membership.id),
            "user_id": str(membership.user_id),
            "role": membership.role,
            "invited_by_id": str(membership.invited_by_id) if membership.invited_by_id else None,
            "invite_accepted_at": (
                membership.invite_accepted_at.isoformat()
                if membership.invite_accepted_at
                else None
            ),
        },
    )


def on_team_invitation_created(invitation):
    """Dispatch ``team.invitation.created`` for a newly created TeamInvitation."""
    dispatch_event(
        team=invitation.team,
        event_type=WebhookEvent.TEAM_INVITATION_CREATED,
        data={
            "team_id": str(invitation.team_id),
            "invitation_id": str(invitation.id),
            "email": invitation.email,
            "user_id": str(invitation.user_id) if invitation.user_id else None,
            "role": invitation.role,
            "invited_by_id": str(invitation.invited_by_id),
            "expires_at": (
                invitation.expires_at.isoformat()
                if invitation.expires_at
                else None
            ),
        },
    )


def on_user_profile_updated(user, changed_fields):
    """Dispatch ``user.profile.updated`` once per active team the user belongs to.

    Only dispatches to teams where the user has an active, non-expired membership
    and the team itself is active.
    """
    from mainapp.models.teams import TeamMembership

    now = timezone.now()
    memberships = TeamMembership.objects.filter(
        user=user,
        team__is_active=True,
    ).exclude(
        access_expires_at__lte=now,
    ).select_related("team")

    data = {
        "user_id": str(user.id),
        "changed_fields": list(changed_fields),
        "updated_at": now.isoformat(),
    }

    for membership in memberships:
        dispatch_event(
            team=membership.team,
            event_type=WebhookEvent.USER_PROFILE_UPDATED,
            data=data,
        )
