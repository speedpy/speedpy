"""Canonical subscription plan registry.

This is the **single source of truth** for plans across SpeedPy: it drives the
pricing page, the billing/upgrade UI, feature gating, and the provider catalog
management commands (``setup_stripe_catalog`` / ``setup_paddle_catalog``). Keep
provider product/price definitions here so Stripe/Paddle never drift from the
application's own plan definitions.

Application code should read plan configuration through :func:`get_plan_config`
(or the ``Team.get_plan_config`` helper) and the billing helpers in
``mainapp.billing`` rather than hard-coding limits or prices.

Provider price IDs are read from settings/env via :func:`_price_id` so that a
missing price ID never breaks free-plan behaviour, billing-disabled installs, or
tests. The values shipped here are generic, clearly-placeholder defaults — fork
owners should tune prices/limits (and run the catalog commands) before launch.
"""

from django.conf import settings

DEFAULT_PLAN_KEY = "free"

# Providers we know how to render catalog/price metadata for.
PROVIDERS = ("stripe", "paddle")

# Billing intervals exposed in the UI and catalog commands.
INTERVALS = ("monthly", "yearly")


def _price_id(env_key):
    """Read a provider price ID from settings, returning ``""`` if unset.

    A missing price ID must never raise — it simply means that plan/interval is
    not yet available for checkout (the UI and checkout views guard on this).
    """
    return getattr(settings, env_key, "") or ""


SUBSCRIPTION_PLANS = {
    "free": {
        "key": "free",
        "name": "Free",
        "description": "For hobby projects and testing. The basics to get started.",
        "price_monthly": 0,
        "price_yearly": 0,
        "is_paid": False,
        "is_contact": False,
        "features": [
            "Basic features",
            "Community support",
            "One project",
        ],
        "limits": {
            "max_team_members": 3,
        },
        "provider_prices": {
            "stripe": {"monthly": "", "yearly": ""},
            "paddle": {"monthly": "", "yearly": ""},
        },
    },
    "pro": {
        "key": "pro",
        "name": "Pro",
        "description": "For small teams shipping real products.",
        "price_monthly": 19,
        "price_yearly": 190,
        "is_paid": True,
        "is_contact": False,
        "features": [
            "Everything in Free",
            "Up to 10 team members",
            "Priority email support",
        ],
        "limits": {
            "max_team_members": 10,
        },
        "provider_prices": {
            "stripe": {
                "monthly": _price_id("STRIPE_PRICE_PRO_MONTHLY"),
                "yearly": _price_id("STRIPE_PRICE_PRO_YEARLY"),
            },
            "paddle": {
                "monthly": _price_id("PADDLE_PRICE_PRO_MONTHLY"),
                "yearly": _price_id("PADDLE_PRICE_PRO_YEARLY"),
            },
        },
    },
    "business": {
        "key": "business",
        "name": "Business",
        "description": "For growing teams that need more room.",
        "price_monthly": 49,
        "price_yearly": 490,
        "is_paid": True,
        "is_contact": False,
        "features": [
            "Everything in Pro",
            "Up to 25 team members",
            "Priority support",
        ],
        "limits": {
            "max_team_members": 25,
        },
        "provider_prices": {
            "stripe": {
                "monthly": _price_id("STRIPE_PRICE_BUSINESS_MONTHLY"),
                "yearly": _price_id("STRIPE_PRICE_BUSINESS_YEARLY"),
            },
            "paddle": {
                "monthly": _price_id("PADDLE_PRICE_BUSINESS_MONTHLY"),
                "yearly": _price_id("PADDLE_PRICE_BUSINESS_YEARLY"),
            },
        },
    },
    "enterprise": {
        "key": "enterprise",
        "name": "Enterprise",
        "description": "For organisations with custom needs.",
        # Contact-us tier: no self-serve checkout, no provider price IDs.
        "price_monthly": None,
        "price_yearly": None,
        "is_paid": True,
        "is_contact": True,
        "features": [
            "Everything in Business",
            "Unlimited team members",
            "SAML / SSO",
            "Dedicated support",
        ],
        "limits": {
            "max_team_members": None,  # unlimited
        },
        "provider_prices": {
            "stripe": {"monthly": "", "yearly": ""},
            "paddle": {"monthly": "", "yearly": ""},
        },
    },
}

# Kept for ``Team.plan`` choices (existing migrations reference this name).
SUBSCRIPTION_PLANS_CHOICES = [
    (plan_key, plan_object.get("name"))
    for plan_key, plan_object in SUBSCRIPTION_PLANS.items()
]


def get_plan_config(plan_key):
    """Return the config dict for a plan key, falling back to the free plan.

    Falling back (rather than raising) keeps callers fail-safe: an unknown or
    stale plan key resolves to the free plan's limits/features instead of
    crashing or silently granting paid access.
    """
    return SUBSCRIPTION_PLANS.get(plan_key, SUBSCRIPTION_PLANS[DEFAULT_PLAN_KEY])


def get_public_plans():
    """Return the ordered list of plan config dicts for public rendering.

    Order follows declaration order (free first), which is the order the pricing
    page and billing UI render plans in.
    """
    return list(SUBSCRIPTION_PLANS.values())


def get_paid_plans():
    """Return the ordered list of paid (non-free) plan config dicts."""
    return [cfg for cfg in SUBSCRIPTION_PLANS.values() if cfg.get("is_paid")]


def get_provider_price_id(provider, plan_key, interval):
    """Return the provider price ID for a plan/interval, or ``""`` if unset.

    ``""`` means "not available for checkout" — callers must treat it as a
    blocked action, never as a free grant.
    """
    cfg = SUBSCRIPTION_PLANS.get(plan_key)
    if not cfg:
        return ""
    return cfg.get("provider_prices", {}).get(provider, {}).get(interval, "") or ""


def get_plan_for_provider_price_id(provider, price_id):
    """Resolve ``(plan_key, interval)`` from a provider price ID.

    Returns ``(None, None)`` when the price ID is unknown/unset so callers never
    silently grant access for an unrecognised price (fail-closed).
    """
    if not price_id:
        return None, None
    for plan_key, cfg in SUBSCRIPTION_PLANS.items():
        prices = cfg.get("provider_prices", {}).get(provider, {})
        for interval in INTERVALS:
            if prices.get(interval) and prices[interval] == price_id:
                return plan_key, interval
    return None, None


def plan_has_feature(plan_key, feature):
    """Whether a plan's ``features`` list contains ``feature`` (exact match)."""
    return feature in get_plan_config(plan_key).get("features", [])


def get_plan_limit(plan_key, limit):
    """Return a named limit for a plan.

    Returns ``None`` when the limit is unset, which by convention means
    "unlimited" for numeric quota limits.
    """
    return get_plan_config(plan_key).get("limits", {}).get(limit)
