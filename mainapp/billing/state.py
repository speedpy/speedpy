"""Runtime billing state and feature gating.

This module is the single place application code asks "what can this account do
right now?". It resolves the billable account (Team or User), the relevant
subscription, the three-state billing status (enabled / grace / disabled), and
feature/limit checks — so views, forms, and tasks never read provider state
directly.

Three runtime states (mirrors the proven pattern from the sibling project):

- ``ENABLED``  — everything works (subject to plan quotas).
- ``GRACE``    — paid features still work, but creating new records is blocked.
- ``DISABLED`` — paid runtime features are off (fail closed).
"""

from django.conf import settings
from django.utils import timezone

from mainapp.models import BillingSubscription
from mainapp.models.billing import BILLABLE_TEAM, BILLABLE_USER
from mainapp.subscription_plans import (
    DEFAULT_PLAN_KEY,
    get_plan_config,
    get_plan_limit,
    plan_has_feature,
)

# Runtime billing states.
ENABLED = "enabled"
GRACE = "grace"
DISABLED = "disabled"


def is_billing_enabled():
    return getattr(settings, "SPEEDPY_BILLING_ENABLED", False)


def _is_team(billable):
    from mainapp.models import Team

    return isinstance(billable, Team)


def billable_token(billable):
    """Return the ``(billable_type, billable_id)`` token pair for a billable."""
    billable_type = BILLABLE_TEAM if _is_team(billable) else BILLABLE_USER
    return billable_type, str(billable.pk)


def get_billable_for_user(user):
    """Resolve the billable account for a user.

    Team when teams are enabled (the user's default team, may be None), the user
    themselves when teams are disabled.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
        from mainapp.models import get_default_team_for_user

        return get_default_team_for_user(user)
    return user


def get_billable_for_request(request):
    return get_billable_for_user(getattr(request, "user", None))


def _subscriptions_for(billable):
    billable_type, billable_id = billable_token(billable)
    return BillingSubscription.objects.filter(
        billable_type=billable_type, billable_id=billable_id
    )


def get_current_subscription(billable):
    """Most recent subscription row of any status, or None."""
    if billable is None:
        return None
    return _subscriptions_for(billable).order_by("-created_at").first()


def get_active_subscription(billable):
    """Most relevant active-ish subscription (active/past_due/paused), or None."""
    if billable is None:
        return None
    return (
        _subscriptions_for(billable)
        .filter(status__in=BillingSubscription.ACTIVE_ISH_STATUSES)
        .order_by("-created_at")
        .first()
    )


def has_active_ish_subscription(billable):
    return get_active_subscription(billable) is not None


def _subscription_confers_access(sub, now=None):
    """Whether a subscription still confers its paid plan.

    True while active-ish (active/past_due/paused) or canceled-but-within the
    paid-through period. Mirrors the granting branches of ``get_billing_state``
    (without calling it, to avoid recursion via ``effective_plan_key``).
    """
    if sub is None or not sub.plan_key:
        return False
    if sub.status in BillingSubscription.ACTIVE_ISH_STATUSES:
        return True
    if sub.status == BillingSubscription.STATUS_CANCELED:
        now = now or timezone.now()
        return bool(sub.current_period_ends_at and now < sub.current_period_ends_at)
    return False


def effective_plan_key(billable):
    """The plan key currently in effect for a billable.

    Team mode reads ``Team.plan`` (kept in sync by plan application). User mode
    derives the plan from the current subscription while it still confers access
    (active-ish, or canceled within the paid-through period), falling back to free
    — consistent with ``get_billing_state``.
    """
    if billable is None:
        return DEFAULT_PLAN_KEY
    if _is_team(billable):
        return billable.plan or DEFAULT_PLAN_KEY
    sub = get_current_subscription(billable)
    if _subscription_confers_access(sub):
        return sub.plan_key
    return DEFAULT_PLAN_KEY


def get_plan_config_for(billable):
    return get_plan_config(effective_plan_key(billable))


def get_billing_state(billable, now=None):
    """Compute the runtime billing state for a billable account."""
    now = now or timezone.now()

    cfg = get_plan_config_for(billable)
    # Free plan is always enabled — nothing to bill.
    if not cfg.get("is_paid"):
        return ENABLED

    sub = get_current_subscription(billable)
    if sub is None:
        # Paid plan with no subscription row is abnormal — fail closed.
        return DISABLED

    status = sub.status
    if status in (BillingSubscription.STATUS_ACTIVE, BillingSubscription.STATUS_PAUSED):
        return ENABLED

    if status == BillingSubscription.STATUS_PAST_DUE:
        return DISABLED if sub.is_grace_period_expired(now=now) else GRACE

    if status == BillingSubscription.STATUS_CANCELED:
        # Keep paid access until the current period ends; the periodic task
        # downgrades to free shortly after.
        if sub.current_period_ends_at and now < sub.current_period_ends_at:
            return ENABLED
        return DISABLED

    # expired / unknown
    return DISABLED


def can_create_records(billable):
    """Whether the account may create new billable records right now.

    Blocked during grace and while billing-disabled.
    """
    return get_billing_state(billable) == ENABLED


def account_has_feature(billable, feature):
    """Whether the account's effective plan includes a feature.

    Fails closed: when billing is enabled but the runtime state is disabled,
    paid features are denied regardless of the (stale) plan key.
    """
    if get_billing_state(billable) == DISABLED:
        return False
    return plan_has_feature(effective_plan_key(billable), feature)


def account_limit(billable, limit):
    """Return a named numeric limit for the account's effective plan.

    ``None`` means unlimited.
    """
    return get_plan_limit(effective_plan_key(billable), limit)


def over_limit_report(billable):
    """Report which quotas the account currently exceeds.

    Used to render persistent over-limit banners after a downgrade. The
    boilerplate's only built-in quota is team membership; products extend this.
    """
    report = {}
    if billable is None:
        return report
    if _is_team(billable):
        limit = account_limit(billable, "max_team_members")
        if limit is not None:
            count = billable.teammembership_set.count()
            if count > limit:
                report["team_members"] = {"count": count, "limit": limit}
    return report
