from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from post_office import mail
import structlog
from mainapp.models import TeamMembership, TeamInvitation, Team
from mainapp.models.teams import (
    TeamCleanupFailed,
    TeamDeletionBlocked,
    finalize_team_deletion,
    teams_due_for_deletion,
)

logger = structlog.get_logger(__name__)


@shared_task(name="send_team_invitation_email")
def send_team_invitation_email(invitation_id):
    """Send team invitation email via post_office"""
    invitation = TeamInvitation.objects.select_related(
        'team', 'invited_by', 'user'
    ).get(pk=invitation_id)

    is_existing_user = invitation.user is not None

    context = {
        'team_name': invitation.team.name,
        'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.email,
        'role': invitation.get_role_display(),
        'accept_url': f"{settings.SITE_URL}/teams/invitations/{invitation.token}/accept/",
        'decline_url': f"{settings.SITE_URL}/teams/invitations/{invitation.token}/decline/",
        'is_existing_user': is_existing_user,
        'message': invitation.message,
        'expires_at': invitation.expires_at,
    }

    subject = f"You've been invited to join {invitation.team.name}"
    html_message = render_to_string("emails/team_invitation.html", context)

    mail.send(
        invitation.email,
        settings.DEFAULT_FROM_EMAIL,
        html_message=html_message,
        subject=subject,
        context=context,
        priority='now',
    )


@shared_task(name="send_role_change_email")
def send_role_change_email(membership_id, old_role, new_role):
    """Send email when role changes"""
    membership = TeamMembership.objects.select_related('team', 'user').get(pk=membership_id)
    context = {
        'team_name': membership.team.name,
        'old_role': old_role,
        'new_role': new_role,
        'team_url': f"{settings.SITE_URL}/teams/{membership.team.id}/dashboard/",
    }
    subject = f"Your role in {membership.team.name} has changed"
    html_message = render_to_string("emails/team_role_changed.html", context=context)
    mail.send(
        membership.user.email,
        settings.DEFAULT_FROM_EMAIL,
        html_message=html_message,
        subject=subject,
        priority='now',
    )

@shared_task(name="expire_team_memberships")
def expire_team_memberships():
    """Delete team memberships that have expired (access_expires_at in the past)"""
    now = timezone.now()

    # Find all memberships with access_expires_at in the past
    expired_memberships = TeamMembership.objects.filter(
        access_expires_at__isnull=False,
        access_expires_at__lt=now
    ).select_related('team', 'user')

    count = 0
    for membership in expired_memberships:
        logger.info(
            "expiring_team_membership",
            membership_id=membership.id,
            user_id=membership.user_id,
            user_email=membership.user.email,
            team_id=membership.team_id,
            team_name=membership.team.name,
            role=membership.role,
            access_expired_at=membership.access_expires_at.isoformat(),
        )
        membership.delete()
        count += 1

    logger.info("expire_team_memberships_completed", expired_count=count)
    return f"Expired {count} team membership(s)"

@shared_task(name="expire_team_memberships_invitations")
def expire_team_memberships_invitations():
    """Delete team invitations that have expired (expires_at in the past)"""
    now = timezone.now()

    # Find all pending invitations with expires_at in the past
    expired_invitations = TeamInvitation.objects.filter(
        expires_at__isnull=False,
        expires_at__lt=now,
        status="pending"
    ).select_related('team', 'invited_by')

    count = 0
    for invitation in expired_invitations:
        logger.info(
            "expiring_team_invitation",
            invitation_id=invitation.id,
            email=invitation.email,
            team_id=invitation.team_id,
            team_name=invitation.team.name,
            invited_by_id=invitation.invited_by_id,
            invited_by_email=invitation.invited_by.email,
            role=invitation.role,
            status=invitation.status,
            expires_at=invitation.expires_at.isoformat(),
        )
        invitation.delete()
        count += 1

    logger.info("expire_team_invitations_completed", expired_count=count)
    return f"Expired {count} team invitation(s)"

@shared_task(name="purge_scheduled_team_deletions")
def purge_scheduled_team_deletions():
    """Delete the teams whose undo window has run out.

    One team per transaction, each locked with select_for_update, so an undo
    that lands while the task is running either wins the row (and the team is
    skipped) or waits for it. A bulk queryset delete is deliberately not used:
    Django's collector would bypass Team.delete(), and with it the billing
    invariant.
    """
    if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
        return "Teams are disabled"

    from django.db import transaction

    deleted = skipped = 0
    for team_id in list(teams_due_for_deletion().values_list("pk", flat=True)):
        try:
            # The try wraps the atomic block, not the other way round: a hook
            # that fails part way through has already written to the database,
            # and the exception has to leave the block for those writes to roll
            # back. Catching inside would commit half a teardown.
            with transaction.atomic():
                team = (
                    Team.objects.select_for_update()
                    .filter(pk=team_id, deletion_scheduled_at__isnull=False)
                    .first()
                )
                if team is None:
                    # Undone (or already gone) between the scan and the lock.
                    skipped += 1
                    continue
                if team.deletion_scheduled_at > timezone.now():
                    # Undone and re-scheduled further out.
                    skipped += 1
                    continue
                if finalize_team_deletion(team):
                    deleted += 1
                else:
                    skipped += 1
        except (TeamCleanupFailed, TeamDeletionBlocked):
            # Both leave the team whole and still scheduled, so the next run
            # retries. Already logged with the reason at the point of failure.
            skipped += 1

    logger.info(
        "purge_scheduled_team_deletions_completed", deleted=deleted, skipped=skipped
    )
    return f"Deleted {deleted} team(s), skipped {skipped}"
