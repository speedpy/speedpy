"""Periodic billing processing and owner notifications.

``process_billing_subscriptions`` acts on subscriptions whose grace period or
billing period has elapsed:

- past_due beyond grace -> send the billing-disabled email (runtime gating
  already disables paid features; we never mutate user-controlled resource
  fields).
- canceled past the current period end -> downgrade the account to free.
- expired -> downgrade the account to free.

All steps are idempotent and safe to run repeatedly.
"""

import structlog
from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from post_office import mail

from mainapp.billing import plans, state
from mainapp.models import BillingSubscription
from mainapp.subscription_plans import get_plan_config

logger = structlog.get_logger(__name__)


def _notify_emails(billable):
    """Email addresses to notify about billing for a billable account."""
    if billable is None:
        return []
    from mainapp.models import Team

    if isinstance(billable, Team):
        return list(
            billable.teammembership_set.filter(role="owner")
            .select_related("user")
            .values_list("user__email", flat=True)
        )
    email = getattr(billable, "email", None)
    return [email] if email else []


def _send_billing_email(subscription, template, subject):
    billable = subscription.billable
    recipients = _notify_emails(billable)
    if not recipients:
        return
    context = {
        "plan_key": subscription.plan_key,
        "status": subscription.get_status_display(),
        "grace_period_ends_at": subscription.grace_period_ends_at,
        "current_period_ends_at": subscription.current_period_ends_at,
        "site_url": getattr(settings, "SITE_URL", ""),
    }
    try:
        html_message = render_to_string(template, context=context)
    except Exception as exc:  # template optional / fork may remove it
        logger.warning("billing_email_template_missing", template=template, error=str(exc))
        return
    for recipient in recipients:
        mail.send(
            recipient,
            settings.DEFAULT_FROM_EMAIL,
            html_message=html_message,
            subject=subject,
            priority="now",
        )


@shared_task(name="send_billing_grace_started_email")
def send_billing_grace_started_email(subscription_id):
    """Notify owners that payment failed and a grace period has started (once)."""
    sub = BillingSubscription.objects.filter(pk=subscription_id).first()
    if sub is None or sub.grace_started_email_sent:
        return
    _send_billing_email(
        sub,
        "emails/billing_grace_started.html",
        "Payment failed — action needed",
    )
    sub.grace_started_email_sent = True
    sub.save(update_fields=["grace_started_email_sent", "updated_at"])


@shared_task(name="send_billing_disabled_email")
def send_billing_disabled_email(subscription_id):
    """Notify owners that paid features are now disabled (once)."""
    sub = BillingSubscription.objects.filter(pk=subscription_id).first()
    if sub is None or sub.billing_disabled_email_sent:
        return
    _send_billing_email(
        sub,
        "emails/billing_disabled.html",
        "Your subscription is now inactive",
    )
    sub.billing_disabled_email_sent = True
    sub.save(update_fields=["billing_disabled_email_sent", "updated_at"])


@shared_task(name="process_billing_subscriptions")
def process_billing_subscriptions():
    """Periodically downgrade lapsed subscriptions and notify owners."""
    now = timezone.now()
    processed = 0

    # 1) Past-due subscriptions whose grace period has expired -> notify owners
    #    once, mark the subscription expired, and downgrade the account so paid
    #    limits/plan no longer apply (runtime gating already fails closed, but
    #    effective plan/limits must drop too).
    past_due = BillingSubscription.objects.filter(
        status=BillingSubscription.STATUS_PAST_DUE,
        grace_period_ends_at__isnull=False,
        grace_period_ends_at__lte=now,
    )
    for sub in past_due:
        if not sub.billing_disabled_email_sent:
            send_billing_disabled_email.delay(str(sub.pk))
        sub.status = BillingSubscription.STATUS_EXPIRED
        sub.save(update_fields=["status", "updated_at"])
        billable = sub.billable
        if billable is not None and get_plan_config(
            state.effective_plan_key(billable)
        ).get("is_paid"):
            plans.downgrade_to_free(billable)
        logger.info("billing_grace_expired_downgraded", subscription_id=str(sub.pk))
        processed += 1

    # 2) Canceled subscriptions past their current period end -> downgrade.
    canceled = BillingSubscription.objects.filter(
        status=BillingSubscription.STATUS_CANCELED,
        current_period_ends_at__isnull=False,
        current_period_ends_at__lte=now,
    )
    for sub in canceled:
        billable = sub.billable
        if billable is not None and get_plan_config(
            state.effective_plan_key(billable)
        ).get("is_paid"):
            plans.downgrade_to_free(billable)
            logger.info(
                "billing_downgraded_after_cancellation",
                subscription_id=str(sub.pk),
            )
            processed += 1

    # 3) Expired subscriptions whose account is still on a paid plan -> downgrade.
    expired = BillingSubscription.objects.filter(
        status=BillingSubscription.STATUS_EXPIRED,
    )
    for sub in expired:
        billable = sub.billable
        if billable is not None and get_plan_config(
            state.effective_plan_key(billable)
        ).get("is_paid"):
            plans.downgrade_to_free(billable)
            processed += 1

    logger.info("process_billing_subscriptions_completed", processed=processed)
    return f"Processed {processed} billing subscription(s)"
