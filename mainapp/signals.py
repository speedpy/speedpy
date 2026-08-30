# Signal handlers for mainapp.
#
# X-Request-ID was previously added to failure responses here via
# django_structlog signals.  This is now handled by
# speedpycom.api.middleware.RequestIDMiddleware for ALL responses.

from allauth.account.signals import email_confirmed, user_signed_up
from django.db.models.signals import post_save
from django.dispatch import receiver

from mainapp.models.teams import TeamInvitation, TeamMembership
from mainapp.ops_notify import esc, notify_ops
from mainapp.webhooks.business_events import on_team_invitation_created, on_team_member_added


@receiver(post_save, sender=TeamMembership)
def dispatch_team_member_added(sender, instance, created, **kwargs):
    if created:
        on_team_member_added(instance)


@receiver(post_save, sender=TeamInvitation)
def dispatch_team_invitation_created(sender, instance, created, **kwargs):
    if created:
        on_team_invitation_created(instance)


# --- Admin ops notifications (Telegram). No-op unless TELEGRAM_OPS_* is set. ---


@receiver(user_signed_up)
def ops_notify_user_signed_up(request, user, **kwargs):
    notify_ops(f"🆕 <b>New sign up</b>\nEmail: {esc(user.email)}")


@receiver(email_confirmed)
def ops_notify_email_confirmed(request, email_address, **kwargs):
    notify_ops(f"✅ <b>Email confirmed</b>\nEmail: {esc(email_address.email)}")
