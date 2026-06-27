"""SpeedPy billing service package (pluggable Stripe / Paddle).

Application code should gate features and limits through the helpers re-exported
here (or via ``mainapp.billing.state``) rather than reading provider state
directly::

    from mainapp import billing

    if billing.account_has_feature(team, "priority_support"):
        ...
    allowed = billing.can_create_records(team)

Provider specifics live in the adapters (``stripe``/``paddle``) behind the common
interface in ``base`` and are selected by ``registry.get_adapter``.
"""

from mainapp.billing.state import (
    ENABLED,
    GRACE,
    DISABLED,
    is_billing_enabled,
    billable_token,
    get_billable_for_user,
    get_billable_for_request,
    get_current_subscription,
    get_active_subscription,
    has_active_ish_subscription,
    effective_plan_key,
    get_plan_config_for,
    get_billing_state,
    can_create_records,
    account_has_feature,
    account_limit,
    over_limit_report,
)

__all__ = [
    "ENABLED",
    "GRACE",
    "DISABLED",
    "is_billing_enabled",
    "billable_token",
    "get_billable_for_user",
    "get_billable_for_request",
    "get_current_subscription",
    "get_active_subscription",
    "has_active_ish_subscription",
    "effective_plan_key",
    "get_plan_config_for",
    "get_billing_state",
    "can_create_records",
    "account_has_feature",
    "account_limit",
    "over_limit_report",
]
