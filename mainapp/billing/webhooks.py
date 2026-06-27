"""Shared inbound-webhook helpers: idempotency and subscription state sync.

Provider adapters parse their own payloads, then hand a normalized dict to
:func:`apply_subscription_update` so the local subscription row, grace period,
and account plan are updated the same way regardless of provider. All updates are
idempotent and safe to receive repeatedly / out of order.
"""

from datetime import timedelta

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from mainapp.billing import plans
from mainapp.models import BillingEventLog, BillingSubscription, resolve_billable

logger = structlog.get_logger(__name__)


def already_processed(provider, event_id):
    """Record an event for idempotent processing.

    Returns ``True`` if this (provider, event_id) was already seen (caller should
    skip processing), ``False`` if it is new (caller should process it).
    Events without an id are never deduped (always processed).
    """
    if not event_id:
        return False
    try:
        with transaction.atomic():
            BillingEventLog.objects.create(provider=provider, event_id=event_id)
        return False
    except IntegrityError:
        return True


def record_event_meta(provider, event_id, event_type, payload):
    """Attach type/payload metadata and a processed timestamp to the event log."""
    if not event_id:
        return
    BillingEventLog.objects.filter(provider=provider, event_id=event_id).update(
        event_type=event_type or "",
        payload=payload or {},
        processed_at=timezone.now(),
    )


def _grace_days():
    return getattr(settings, "SPEEDPY_BILLING_GRACE_PERIOD_DAYS", 30)


def apply_subscription_update(provider, data):
    """Create/update the local subscription row and sync the account plan.

    ``data`` is a provider-neutral dict produced by an adapter:
        billable_type, billable_id, provider_subscription_id,
        provider_customer_id, provider_price_id, provider_product_id,
        plan_key, interval, status, raw_provider_status,
        current_period_starts_at, current_period_ends_at,
        trial_starts_at, trial_ends_at, canceled_at,
        cancellation_effective_at, raw_payload

    ``status`` is the local status or ``None`` (unmapped → ignored, never grants).
    ``plan_key`` is the resolved plan or ``None`` (unknown price → not applied).
    """
    status = data.get("status")
    if status is None:
        logger.warning(
            "billing_webhook_unknown_status",
            provider=provider,
            raw_status=data.get("raw_provider_status"),
            subscription_id=data.get("provider_subscription_id"),
        )
        return None

    billable = resolve_billable(data.get("billable_type"), data.get("billable_id"))
    if billable is None:
        logger.warning(
            "billing_webhook_unresolved_billable",
            provider=provider,
            billable_type=data.get("billable_type"),
            billable_id=data.get("billable_id"),
            subscription_id=data.get("provider_subscription_id"),
        )
        return None

    sub_id = data.get("provider_subscription_id") or ""
    plan_key = data.get("plan_key")

    with transaction.atomic():
        sub = (
            BillingSubscription.objects.select_for_update()
            .filter(provider=provider, provider_subscription_id=sub_id)
            .first()
            if sub_id
            else None
        )
        if sub is None:
            sub = BillingSubscription(
                provider=provider, provider_subscription_id=sub_id
            )

        # Reject stale / out-of-order events: if we've already applied a newer
        # provider event to this row, ignore this older one so a delayed
        # "active" can't re-grant access after a later "canceled"/"expired".
        event_at = data.get("event_occurred_at")
        if sub.pk and sub.last_event_at and event_at and event_at < sub.last_event_at:
            logger.info(
                "billing_webhook_stale_event_ignored",
                provider=provider,
                subscription_id=sub_id,
                event_at=event_at.isoformat(),
                last_event_at=sub.last_event_at.isoformat(),
            )
            return sub

        previous_status = sub.status if sub.pk else None

        sub.billable_type = data["billable_type"]
        sub.billable_id = data["billable_id"]
        sub.provider_customer_id = data.get("provider_customer_id", "") or ""
        sub.provider_price_id = data.get("provider_price_id", "") or ""
        sub.provider_product_id = data.get("provider_product_id", "") or ""
        # Fail closed: the stored plan is only ever a registry-recognised plan.
        # An unknown price clears plan_key (never preserves a stale paid plan),
        # and the apply step below downgrades the account.
        sub.plan_key = plan_key or ""
        if data.get("interval"):
            sub.billing_interval = data["interval"]
        sub.status = status
        sub.raw_provider_status = data.get("raw_provider_status", "") or ""
        sub.current_period_starts_at = data.get("current_period_starts_at")
        sub.current_period_ends_at = data.get("current_period_ends_at")
        sub.trial_starts_at = data.get("trial_starts_at")
        sub.trial_ends_at = data.get("trial_ends_at")
        sub.canceled_at = data.get("canceled_at")
        sub.cancellation_effective_at = data.get("cancellation_effective_at")
        if event_at:
            sub.last_event_at = event_at
        sub.raw_payload = data.get("raw_payload", {}) or {}

        # Grace-period bookkeeping on entering past_due.
        entering_past_due = (
            status == BillingSubscription.STATUS_PAST_DUE
            and previous_status != BillingSubscription.STATUS_PAST_DUE
        )
        if status == BillingSubscription.STATUS_PAST_DUE:
            if not sub.past_due_started_at:
                sub.past_due_started_at = timezone.now()
            if not sub.grace_period_ends_at:
                sub.grace_period_ends_at = sub.past_due_started_at + timedelta(
                    days=_grace_days()
                )
        else:
            # Recovered (or no longer past_due): clear grace bookkeeping.
            sub.past_due_started_at = None
            sub.grace_period_ends_at = None
            sub.grace_started_email_sent = False
            sub.billing_disabled_email_sent = False

        sub.save()

    # Apply plan to the account (outside the row lock).
    if status in (BillingSubscription.STATUS_ACTIVE, BillingSubscription.STATUS_PAUSED):
        if plan_key:
            plans.apply_plan_to_billable(billable, plan_key)
        else:
            # Active/paused but the price isn't in the registry (e.g. catalog
            # drift or a provider-side price swap). Fail closed: do not keep
            # granting a paid plan — downgrade to free and log loudly so the
            # operator re-syncs the catalog.
            logger.error(
                "billing_webhook_unknown_price_downgrading",
                provider=provider,
                price_id=data.get("provider_price_id"),
                subscription_id=sub_id,
            )
            plans.downgrade_to_free(billable)
    elif status == BillingSubscription.STATUS_EXPIRED:
        plans.downgrade_to_free(billable)
    # past_due / canceled: keep the current plan; the grace/period logic and the
    # periodic task decide when to downgrade.

    # Fire the grace-started email once, when first entering past_due.
    if entering_past_due and not sub.grace_started_email_sent:
        from mainapp.tasks.billing import send_billing_grace_started_email

        send_billing_grace_started_email.delay(str(sub.pk))

    logger.info(
        "billing_subscription_synced",
        provider=provider,
        subscription_id=sub_id,
        status=status,
        plan_key=sub.plan_key,
        billable_type=sub.billable_type,
        billable_id=sub.billable_id,
    )
    return sub
