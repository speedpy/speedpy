import structlog
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


@receiver(post_save, sender="account.EmailAddress")
def sync_email_confirmed(sender, instance, **kwargs):
    """Keep User.is_email_confirmed in sync with the primary allauth EmailAddress."""
    if not instance.primary:
        return

    user = instance.user
    if user.is_email_confirmed != instance.verified:
        user.is_email_confirmed = instance.verified
        user.save(update_fields=["is_email_confirmed"])
        logger.info(
            "email_confirmed_synced",
            user_id=str(user.id),
            verified=instance.verified,
        )


@receiver(post_delete, sender="account.EmailAddress")
def clear_email_confirmed_on_delete(sender, instance, **kwargs):
    """Clear is_email_confirmed when a verified primary EmailAddress is deleted."""
    if not instance.primary or not instance.verified:
        return

    user = instance.user
    if user.is_email_confirmed:
        user.is_email_confirmed = False
        user.save(update_fields=["is_email_confirmed"])
        logger.info(
            "email_confirmed_cleared",
            user_id=str(user.id),
        )
