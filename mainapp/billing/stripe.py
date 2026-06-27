"""SpeedPy-owned Stripe adapter using the official Stripe Python SDK.

Launches checkout via a server-created Stripe Checkout Session (redirect),
opens the Stripe billing portal, verifies webhook signatures with
``stripe.Webhook.construct_event``, and maps Stripe subscription statuses onto
local statuses conservatively. The billable account is carried in checkout
metadata (and propagated to the subscription) so webhooks never trust the email.
"""

from datetime import datetime, timezone as dt_timezone

import stripe
import structlog
from django.conf import settings

from mainapp.billing import webhooks
from mainapp.billing.base import BillingAdapter, CheckoutResult
from mainapp.billing.signing import sign_account, unsign_account
from mainapp.models import BillingSubscription
from mainapp.subscription_plans import get_plan_for_provider_price_id

logger = structlog.get_logger(__name__)

# Stripe status -> local status. Conservative: unknown/pre-activation -> None
# (ignored, never grants); terminal-failure "unpaid" -> expired (downgrade).
_STRIPE_STATUS_MAP = {
    "active": BillingSubscription.STATUS_ACTIVE,
    "trialing": BillingSubscription.STATUS_ACTIVE,
    "past_due": BillingSubscription.STATUS_PAST_DUE,
    "paused": BillingSubscription.STATUS_PAUSED,
    "canceled": BillingSubscription.STATUS_CANCELED,
    "unpaid": BillingSubscription.STATUS_EXPIRED,
}


def _ts(value):
    """Convert a Stripe unix timestamp to an aware datetime, or None."""
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=dt_timezone.utc)


class StripeAdapter(BillingAdapter):
    provider = "stripe"

    @classmethod
    def is_configured(cls):
        return bool(getattr(settings, "STRIPE_SECRET_KEY", ""))

    def _client(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe

    # -- Checkout / portal ------------------------------------------------

    def create_checkout(
        self,
        *,
        billable,
        billable_type,
        billable_id,
        plan_key,
        interval,
        price_id,
        customer_email,
        success_url,
        cancel_url,
    ):
        client = self._client()
        metadata = {
            # Signed token is the trusted account reference (defense in depth —
            # Stripe metadata is server-set, but we verify uniformly).
            "account_token": sign_account(billable_type, billable_id),
            "billable_type": billable_type,
            "billable_id": billable_id,
            "plan_key": plan_key,
            "interval": interval,
        }
        session = client.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=customer_email or None,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            # Propagate to the subscription so every subscription.* webhook
            # carries the account reference too.
            subscription_data={"metadata": metadata},
        )
        return CheckoutResult(mode=CheckoutResult.MODE_REDIRECT, url=session.url)

    def create_portal_session(self, *, customer_id, return_url=None):
        if not customer_id:
            return None
        try:
            client = self._client()
            session = client.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return session.url
        except stripe.StripeError as exc:
            logger.error("stripe_portal_session_error", error=str(exc))
            return None

    # -- Webhooks ---------------------------------------------------------

    def verify_and_parse_webhook(self, request):
        secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        signature = request.headers.get("Stripe-Signature", "")
        if not secret or not signature:
            return None
        try:
            event = stripe.Webhook.construct_event(
                request.body, signature, secret
            )
        except (ValueError, stripe.SignatureVerificationError):
            return None
        return event

    def get_event_id(self, event):
        return event.get("id") or ""

    def get_event_type(self, event):
        return event.get("type") or ""

    def process_event(self, event):
        event_type = event.get("type", "")
        obj = event.get("data", {}).get("object", {}) or {}

        if event_type == "checkout.session.completed":
            subscription_id = obj.get("subscription")
            if not subscription_id:
                return
            try:
                subscription = self._client().Subscription.retrieve(subscription_id)
            except stripe.StripeError as exc:
                logger.error("stripe_subscription_retrieve_error", error=str(exc))
                return
            # Prefer the session metadata (set at checkout) for account resolution.
            normalized = self._normalize_subscription(
                subscription, event, fallback_metadata=obj.get("metadata") or {}
            )
            webhooks.apply_subscription_update(self.provider, normalized)
            return

        if event_type.startswith("customer.subscription."):
            normalized = self._normalize_subscription(obj, event)
            webhooks.apply_subscription_update(self.provider, normalized)
            return

        # Other events (invoice.*, etc.) surface as subscription.updated, so we
        # don't need to handle them separately.

    def _normalize_subscription(self, subscription, raw_event, fallback_metadata=None):
        metadata = dict(fallback_metadata or {})
        metadata.update(subscription.get("metadata") or {})

        item = ((subscription.get("items") or {}).get("data") or [{}])[0]
        price = item.get("price") or {}
        price_id = price.get("id", "") or ""
        product_id = price.get("product", "") or ""

        # The granted plan is resolved ONLY from a registry-recognised provider
        # price (fail closed on unknown prices). metadata.plan_key is not trusted
        # to grant a tier; interval is non-granting so a metadata fallback is ok.
        plan_key, interval = get_plan_for_provider_price_id(self.provider, price_id)
        if not interval:
            interval = metadata.get("interval") or None

        raw_status = subscription.get("status", "")
        # Billable resolved from the server-signed token only.
        billable_type, billable_id = unsign_account(metadata.get("account_token"))

        return {
            "billable_type": billable_type,
            "billable_id": billable_id,
            "event_occurred_at": _ts(raw_event.get("created")),
            "provider_subscription_id": subscription.get("id", ""),
            "provider_customer_id": subscription.get("customer", ""),
            "provider_price_id": price_id,
            "provider_product_id": product_id,
            "plan_key": plan_key,
            "interval": interval,
            "status": _STRIPE_STATUS_MAP.get(raw_status),
            "raw_provider_status": raw_status,
            "current_period_starts_at": _ts(subscription.get("current_period_start")),
            "current_period_ends_at": _ts(subscription.get("current_period_end")),
            "trial_starts_at": _ts(subscription.get("trial_start")),
            "trial_ends_at": _ts(subscription.get("trial_end")),
            "canceled_at": _ts(subscription.get("canceled_at")),
            "cancellation_effective_at": _ts(subscription.get("cancel_at")),
            "raw_payload": dict(raw_event),
        }
