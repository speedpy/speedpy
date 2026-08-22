"""Email delivery events and the suppression list.

Two models with deliberately different characters:

``EmailEvent`` is an **append-only log**. It records what the ESP told us
happened to a message — sent, delivered, bounced, complained, delayed. It is
diagnostic data and it contains personal data (a recipient address, and an SMTP
diagnostic that often quotes it), so it should be covered by whatever
retention purge your project runs.

``SuppressedEmail`` is **enforcement**. An address on this list is never sent to
again. It is written from a permanent bounce or any complaint, and it is
deliberately **global rather than per-team**: the asset being protected is your
ESP account reputation, which is shared by every tenant, so one customer's bad
address has to stop you mailing it from every account. ``EmailEvent`` still
records a team where one can be resolved (see
``SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER``), so a customer can be shown which of their
contacts are undeliverable without the suppression list itself being scoped.

The distinction that matters most: **a transient bounce never suppresses.** A
full mailbox, a greylist or a temporary DNS failure is not a reason to stop
writing to somebody permanently, and treating it as one would quietly destroy a
customer's ability to reach real people.
"""

from django.db import models

from speedpycom.models.base import BaseModel


class EmailEvent(BaseModel):
    """One delivery event reported by the ESP. Append-only."""

    class Type(models.TextChoices):
        SEND = "send"
        DELIVERY = "delivery"
        BOUNCE = "bounce"
        COMPLAINT = "complaint"
        REJECT = "reject"
        DELIVERY_DELAY = "delivery_delay"
        RENDERING_FAILURE = "rendering_failure"
        OTHER = "other"

    class BounceType(models.TextChoices):
        PERMANENT = "permanent"
        TRANSIENT = "transient"
        UNDETERMINED = "undetermined"

    #: SNS message id. Unique, and the whole idempotency story: SNS delivers at
    #: least once, so the same event can arrive several times.
    provider_message_id = models.CharField(max_length=255, unique=True)
    #: The ESP's id for the MESSAGE (not the event) — several events share it,
    #: which is how a bounce is tied back to the send that caused it.
    message_id = models.CharField(max_length=255, blank=True, db_index=True)

    event_type = models.CharField(
        max_length=20, choices=Type.choices, default=Type.OTHER, db_index=True
    )
    recipient = models.EmailField(db_index=True)
    bounce_type = models.CharField(
        max_length=20, choices=BounceType.choices, blank=True
    )
    #: SES's finer classification, e.g. "General", "Suppressed", "NoEmail".
    bounce_subtype = models.CharField(max_length=50, blank=True)
    #: The SMTP response or complaint feedback type, for diagnosis.
    diagnostic = models.TextField(blank=True)

    #: When the ESP says it happened, which is not when we received it.
    occurred_at = models.DateTimeField(null=True, blank=True)

    #: Best-effort attribution. ESP events carry no tenant, so it is resolved
    #: from the recipient by the project's own resolver where one is configured
    #: (``SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER``) and left null otherwise — never
    #: guessed. Nullable and optional: a project without tenants simply never
    #: sets a resolver.
    team = models.ForeignKey(
        "mainapp.Team", null=True, blank=True, on_delete=models.SET_NULL
    )

    #: Retained for diagnosis. Personal data — blank it in your retention purge
    #: rather than deleting the row, so ``provider_message_id`` survives as a
    #: tombstone and a redelivered notification is still a no-op.
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "event_type"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} for {self.recipient}"

    @property
    def should_suppress(self):
        """Whether this event means we must stop mailing the recipient.

        A permanent bounce or ANY complaint suppresses. A transient bounce does
        not — see the module docstring; this is the single most important line in
        the file.
        """
        if self.event_type == self.Type.COMPLAINT:
            return True
        return (
            self.event_type == self.Type.BOUNCE
            and self.bounce_type == self.BounceType.PERMANENT
        )


class SuppressedEmail(BaseModel):
    """An address we will not send to again. Global, not per-team."""

    class Reason(models.TextChoices):
        HARD_BOUNCE = "hard_bounce"
        COMPLAINT = "complaint"
        MANUAL = "manual"

    #: Stored lowercase; ``speedpycom/services/email_events.py`` normalizes on the way in
    #: so a differently-cased address cannot slip past the guard.
    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    #: The event that caused it, kept for "why is this address blocked?".
    detail = models.TextField(blank=True)
    #: Cleared by an operator who has a reason to try again.
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} ({self.reason})"

    @property
    def is_active(self):
        return self.released_at is None
