"""Adapter selection.

``get_adapter()`` returns the adapter for the currently configured provider
(used to start new checkout/portal actions). ``get_adapter_for_provider()``
returns a specific provider's adapter regardless of the current configuration —
needed because existing subscriptions retain whichever provider created them, and
each provider's webhook must be processed by its own adapter even after the
configured provider changes.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _adapter_class_for(provider):
    if provider == "stripe":
        from mainapp.billing.stripe import StripeAdapter

        return StripeAdapter
    if provider == "paddle":
        from mainapp.billing.paddle import PaddleAdapter

        return PaddleAdapter
    return None


def get_adapter_for_provider(provider):
    """Return an adapter instance for a specific provider, or raise.

    Raises ``ImproperlyConfigured`` for an unknown provider.
    """
    adapter_cls = _adapter_class_for(provider)
    if adapter_cls is None:
        raise ImproperlyConfigured(f"Unknown billing provider: {provider!r}")
    return adapter_cls()


def get_adapter():
    """Return the adapter for the configured provider for new actions.

    Raises ``ImproperlyConfigured`` when billing is enabled without a valid,
    configured provider — surfacing misconfiguration loudly rather than silently
    failing checkout.
    """
    if not getattr(settings, "SPEEDPY_BILLING_ENABLED", False):
        raise ImproperlyConfigured("Billing is disabled (SPEEDPY_BILLING_ENABLED=False).")

    provider = getattr(settings, "SPEEDPY_BILLING_PROVIDER", "") or ""
    adapter_cls = _adapter_class_for(provider)
    if adapter_cls is None:
        raise ImproperlyConfigured(
            "SPEEDPY_BILLING_PROVIDER must be 'stripe' or 'paddle' when billing "
            f"is enabled (got {provider!r})."
        )

    if not adapter_cls.is_configured():
        raise ImproperlyConfigured(
            f"Billing provider {provider!r} is selected but its credentials are "
            "not configured."
        )

    return adapter_cls()
