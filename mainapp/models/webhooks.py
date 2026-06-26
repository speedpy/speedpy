import secrets

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from encrypted_fields.fields import EncryptedCharField

from mainapp.webhooks.events import WebhookEvent
from .teams import TeamModel

DEFAULT_ROTATION_OVERLAP_SECONDS = 86400  # 24 hours


def _validate_https_url(value):
    """Validate that the URL uses HTTPS."""
    URLValidator(schemes=["https"])(value)


def _validate_webhook_events(value):
    """Validate that all events in the list are known or the wildcard '*'."""
    if not isinstance(value, list):
        raise ValidationError(_("Events must be a list."))
    for event in value:
        if not isinstance(event, str):
            raise ValidationError(
                _("Each event must be a string, got %(type)s."),
                params={"type": type(event).__name__},
            )
        if event != "*" and event not in WebhookEvent.ALL:
            raise ValidationError(
                _("Unknown event type: %(event)s"),
                params={"event": event},
            )


def _generate_secret():
    return secrets.token_urlsafe(32)


class WebhookEndpoint(TeamModel):
    """
    A team-scoped webhook subscription endpoint.

    The signing secret is stored encrypted at rest using
    django-fernet-encrypted-fields, so the delivery worker can retrieve
    the raw secret for HMAC-SHA256 signature computation.
    """

    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Optional human-readable label for this endpoint."),
    )
    url = models.URLField(
        max_length=2048,
        validators=[_validate_https_url],
        help_text=_("HTTPS URL that receives webhook payloads."),
    )
    events = models.JSONField(
        default=list,
        validators=[_validate_webhook_events],
        help_text=_(
            'List of event types to subscribe to, or ["*"] for all events.'
        ),
    )
    secret = EncryptedCharField(
        max_length=255,
        blank=True,
        help_text=_("Signing secret, encrypted at rest. Auto-generated on creation."),
    )

    previous_secret = EncryptedCharField(
        max_length=255,
        blank=True,
        null=True,
        default=None,
        help_text=_("Previous signing secret kept during rotation overlap window."),
    )
    secret_rotated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the signing secret was last rotated."),
    )
    previous_secret_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the previous secret stops being accepted by verifiers."),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Inactive endpoints do not receive deliveries."),
    )

    class Meta:
        verbose_name = _("Webhook Endpoint")
        verbose_name_plural = _("Webhook Endpoints")
        ordering = ["-created_at"]

    def __str__(self):
        label = self.name or self.url
        return f"{label} ({self.team})"

    def clean(self):
        super().clean()
        if not self.secret:
            self.secret = _generate_secret()

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = _generate_secret()
        super().save(*args, **kwargs)

    @staticmethod
    def get_rotation_overlap_seconds():
        return getattr(
            django_settings,
            "SPEEDPY_WEBHOOK_SECRET_ROTATION_OVERLAP_SECONDS",
            DEFAULT_ROTATION_OVERLAP_SECONDS,
        )

    def rotate_secret(self, overlap_seconds=None):
        """Rotate the signing secret, keeping the old one during the overlap window.

        Moves the current ``secret`` into ``previous_secret``, generates a
        new active secret, and sets rotation/expiry timestamps.  Only one
        previous secret is supported — a second rotation during an active
        overlap replaces the stored previous secret.
        """
        if overlap_seconds is None:
            overlap_seconds = self.get_rotation_overlap_seconds()

        now = timezone.now()
        self.previous_secret = self.secret
        self.secret = _generate_secret()
        self.secret_rotated_at = now
        self.previous_secret_expires_at = now + timezone.timedelta(seconds=overlap_seconds)
        self.save(update_fields=[
            "secret",
            "previous_secret",
            "secret_rotated_at",
            "previous_secret_expires_at",
            "updated_at",
        ])

    def subscribes_to(self, event_type: str) -> bool:
        """Return True if this endpoint should receive the given event."""
        return "*" in self.events or event_type in self.events


class WebhookDelivery(models.Model):
    """
    Log of an individual webhook delivery attempt.

    Uses a regular AutoField PK (not UUID) for efficient ordering and
    indexing on high-volume delivery logs.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        IN_FLIGHT = "in_flight", _("In Flight")
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")
        DISABLED = "disabled", _("Disabled")

    endpoint = models.ForeignKey(
        WebhookEndpoint,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    event_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text=_("Unique event identifier (e.g. evt_<uuid>)."),
    )
    event_type = models.CharField(
        max_length=255,
        db_index=True,
        help_text=_("Dot-separated event type."),
    )
    payload = models.JSONField(
        help_text=_("Full event payload envelope."),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When this delivery is/was scheduled to run."),
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the delivery succeeded."),
    )
    http_status_code = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )
    RESPONSE_BODY_MAX_LENGTH = 4096

    response_body = models.TextField(
        blank=True,
        default="",
        help_text=_("Truncated response body (max 4 KB)."),
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text=_("Error details if delivery failed."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Webhook Delivery")
        verbose_name_plural = _("Webhook Deliveries")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["endpoint", "status"]),
            models.Index(fields=["event_id"]),
        ]

    def save(self, *args, **kwargs):
        if self.response_body and len(self.response_body) > self.RESPONSE_BODY_MAX_LENGTH:
            self.response_body = self.response_body[: self.RESPONSE_BODY_MAX_LENGTH]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event_type} → {self.endpoint.url} [{self.status}]"
