from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from post_office import mail
import structlog
from mainapp.models import TeamMembership, TeamInvitation

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