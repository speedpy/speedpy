# Signal handlers for mainapp.
#
# X-Request-ID was previously added to failure responses here via
# django_structlog signals.  This is now handled by
# speedpycom.api.middleware.RequestIDMiddleware for ALL responses.

from django.db.models.signals import post_save
from django.dispatch import receiver

from mainapp.models.teams import TeamInvitation, TeamMembership
from mainapp.webhooks.business_events import on_team_invitation_created, on_team_member_added


@receiver(post_save, sender=TeamMembership)
def dispatch_team_member_added(sender, instance, created, **kwargs):
    if created:
        on_team_member_added(instance)


@receiver(post_save, sender=TeamInvitation)
def dispatch_team_invitation_created(sender, instance, created, **kwargs):
    if created:
        on_team_invitation_created(instance)
