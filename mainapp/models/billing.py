"""Provider-neutral billing models.

These tables are the authoritative, local record of billing state. Provider
(Stripe / Paddle) objects and webhook payloads stay implementation details
behind the adapters in ``mainapp.billing``; application code reads SpeedPy plans
and these rows, never the provider directly.

The billable account is either a ``Team`` (when ``SPEEDPY_TEAMS_ENABLED``) or a
``User`` (when teams are disabled). Rather than a generic ContentType relation we
store a stable ``billable_type`` token ("team"/"user") plus the object's UUID in
``billable_id``. Those two values are exactly what we round-trip through provider
checkout metadata / custom data, so webhooks resolve the account without trusting
the provider's customer email.
"""

from django.db import models
from django.utils import timezone

from speedpycom.models import BaseModel


# Billable account types. These string tokens are stored verbatim and also sent
# as provider checkout metadata, so keep them stable.
BILLABLE_TEAM = "team"
BILLABLE_USER = "user"
BILLABLE_TYPE_CHOICES = [
    (BILLABLE_TEAM, "Team"),
    (BILLABLE_USER, "User"),
]

PROVIDER_CHOICES = [
    ("stripe", "Stripe"),
    ("paddle", "Paddle"),
]


def resolve_billable(billable_type, billable_id):
    """Resolve a billable token pair back to its model instance, or ``None``.

    Lazy imports keep this usable from webhook code without import cycles.
    Returns ``None`` for unknown types or missing rows so webhook handlers can
    fail closed instead of raising.
    """
    if not billable_type or not billable_id:
        return None
    if billable_type == BILLABLE_TEAM:
        from mainapp.models import Team

        return Team.objects.filter(pk=billable_id).first()
    if billable_type == BILLABLE_USER:
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=billable_id).first()
    return None


class _BillableMixin(models.Model):
    """Shared billable-account columns and helpers."""

    billable_type = models.CharField(
        max_length=10, choices=BILLABLE_TYPE_CHOICES, db_index=True
    )
    billable_id = models.CharField(max_length=64, db_index=True)

    class Meta:
        abstract = True

    @property
    def billable(self):
        """Resolve the billable account instance (Team or User), or None."""
        return resolve_billable(self.billable_type, self.billable_id)


class BillingCustomer(_BillableMixin, BaseModel):
    """Maps a billable account to a provider customer.

    SpeedPy owns the canonical account↔customer mapping (Paddle's own customer
    model is user-centric, which does not fit team billing). One row per
    (provider, provider_customer_id).
    """

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, db_index=True)
    provider_customer_id = models.CharField(max_length=255, db_index=True, blank=True)
    email = models.EmailField(blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Billing Customer"
        verbose_name_plural = "Billing Customers"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_customer_id"],
                name="uniq_billing_customer_provider_customer",
            ),
        ]
        indexes = [
            models.Index(fields=["billable_type", "billable_id"]),
        ]

    def __str__(self):
        return f"{self.provider}:{self.provider_customer_id} ({self.billable_type}:{self.billable_id})"


class BillingSubscription(_BillableMixin, BaseModel):
    """A subscription sourced from a provider, linked to a billable account.

    We keep **one row per provider subscription id** (rather than a single
    mutable field on the account) so that subscription history is retained,
    duplicate/out-of-order webhooks don't clobber each other, and abnormal states
    (e.g. two active-ish rows) stay visible in admin for manual reconciliation.
    There is deliberately no DB constraint forbidding multiple active-ish rows;
    new checkout is blocked in application code instead.
    """

    # Local status lifecycle (provider statuses are mapped onto these).
    STATUS_ACTIVE = "active"
    STATUS_PAST_DUE = "past_due"
    STATUS_PAUSED = "paused"
    STATUS_CANCELED = "canceled"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    # Statuses that grant (or still grant) paid access.
    ACTIVE_ISH_STATUSES = (STATUS_ACTIVE, STATUS_PAST_DUE, STATUS_PAUSED)

    INTERVAL_CHOICES = [
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, db_index=True)

    # Provider identifiers
    provider_customer_id = models.CharField(max_length=255, db_index=True, blank=True)
    provider_subscription_id = models.CharField(max_length=255, db_index=True, blank=True)
    provider_price_id = models.CharField(max_length=255, blank=True)
    provider_product_id = models.CharField(max_length=255, blank=True)

    # Resolved local plan
    plan_key = models.CharField(max_length=50, db_index=True)
    billing_interval = models.CharField(
        max_length=10, choices=INTERVAL_CHOICES, default="monthly"
    )

    # Status tracking
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True
    )
    raw_provider_status = models.CharField(
        max_length=50, blank=True, help_text="Verbatim status string from the provider"
    )

    # Billing period
    current_period_starts_at = models.DateTimeField(null=True, blank=True)
    current_period_ends_at = models.DateTimeField(null=True, blank=True)

    # Trial
    trial_starts_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    # Cancellation
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancellation_effective_at = models.DateTimeField(null=True, blank=True)

    # Payment failure / grace period
    past_due_started_at = models.DateTimeField(null=True, blank=True)
    grace_period_ends_at = models.DateTimeField(null=True, blank=True)

    # Timestamp of the most recent provider event applied to this row. Used to
    # reject stale / out-of-order webhook events before they re-grant access.
    last_event_at = models.DateTimeField(null=True, blank=True)

    # Most recent relevant webhook payload, for debugging / audit.
    raw_payload = models.JSONField(default=dict, blank=True)

    # Notification de-duplication flags (avoid emailing owners repeatedly).
    grace_started_email_sent = models.BooleanField(default=False)
    billing_disabled_email_sent = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Billing Subscription"
        verbose_name_plural = "Billing Subscriptions"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_subscription_id"],
                name="uniq_billing_subscription_provider_sub",
                condition=~models.Q(provider_subscription_id=""),
            ),
        ]
        indexes = [
            models.Index(fields=["billable_type", "billable_id"]),
        ]

    def __str__(self):
        return f"{self.provider}:{self.provider_subscription_id} [{self.status}]"

    @property
    def is_active_ish(self):
        """Whether this subscription grants (or still grants) paid access."""
        return self.status in self.ACTIVE_ISH_STATUSES

    def is_in_grace_period(self, now=None):
        """True while past_due and the grace period has not yet elapsed."""
        if self.status != self.STATUS_PAST_DUE:
            return False
        if not self.grace_period_ends_at:
            return True
        now = now or timezone.now()
        return now < self.grace_period_ends_at

    def is_grace_period_expired(self, now=None):
        """True when past_due and the grace period has elapsed."""
        if self.status != self.STATUS_PAST_DUE:
            return False
        if not self.grace_period_ends_at:
            return False
        now = now or timezone.now()
        return now >= self.grace_period_ends_at


class BillingEventLog(BaseModel):
    """Idempotency / audit log of inbound provider webhook events.

    A row is created per (provider, event_id) so retried or duplicate webhooks
    are processed exactly once. The raw payload is retained for debugging.
    """

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, db_index=True)
    event_id = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Billing Event Log"
        verbose_name_plural = "Billing Event Logs"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="uniq_billing_event_provider_event",
            ),
        ]

    def __str__(self):
        return f"{self.provider}:{self.event_id} ({self.event_type})"

    def mark_processed(self):
        self.processed_at = timezone.now()
        self.save(update_fields=["processed_at", "updated_at"])
