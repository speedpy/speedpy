"""SpeedPy-owned Paddle (Billing v2) adapter.

A thin, self-contained adapter over the Paddle REST API and webhooks — no
dependency on ``django-paddle-billing``. It verifies ``Paddle-Signature``
directly, maps Paddle subscription statuses onto local statuses conservatively,
launches checkout client-side via Paddle.js, and resolves the billable account
from checkout ``custom_data`` (never from the customer email).
"""

import hashlib
import hmac
import json

import requests
import structlog
from django.conf import settings
from django.utils.dateparse import parse_datetime

from mainapp.billing import webhooks
from mainapp.billing.base import BillingAdapter, CheckoutResult
from mainapp.billing.signing import sign_account, unsign_account
from mainapp.models import BillingSubscription
from mainapp.subscription_plans import get_plan_for_provider_price_id

logger = structlog.get_logger(__name__)

# Paddle status string -> local status. Unknown statuses map to None (never grant).
_PADDLE_STATUS_MAP = {
    "active": BillingSubscription.STATUS_ACTIVE,
    "trialing": BillingSubscription.STATUS_ACTIVE,
    "past_due": BillingSubscription.STATUS_PAST_DUE,
    "paused": BillingSubscription.STATUS_PAUSED,
    "canceled": BillingSubscription.STATUS_CANCELED,
    # Paddle uses "canceled"; accept the British spelling defensively too.
    "cancelled": BillingSubscription.STATUS_CANCELED,
}

_TIMEOUT = 30


def api_base():
    """Return the Paddle API base URL for the configured environment."""
    if getattr(settings, "PADDLE_ENVIRONMENT", "sandbox") == "production":
        return "https://api.paddle.com"
    return "https://sandbox-api.paddle.com"


def verify_webhook_signature(raw_body, signature_header, secret=None):
    """Verify a Paddle ``Paddle-Signature`` header.

    Header format: ``ts=<unix>;h1=<hex hmac>``. The signed payload is
    ``"{ts}:{raw_body}"`` HMAC-SHA256'd with the webhook secret.
    """
    secret = secret if secret is not None else getattr(settings, "PADDLE_WEBHOOK_SECRET", "")
    if not secret or not signature_header:
        return False

    try:
        parts = dict(
            piece.split("=", 1)
            for piece in signature_header.split(";")
            if "=" in piece
        )
    except ValueError:
        return False

    ts = parts.get("ts")
    h1 = parts.get("h1")
    if not ts or not h1:
        return False

    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8")

    signed_payload = f"{ts}:{raw_body}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, h1)


class PaddleAdapter(BillingAdapter):
    provider = "paddle"

    @classmethod
    def is_configured(cls):
        return bool(getattr(settings, "PADDLE_API_KEY", ""))

    def _headers(self):
        return {
            "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
            "Content-Type": "application/json",
        }

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
        """Paddle checkout runs client-side via Paddle.js; return its context."""
        custom_data = {
            # Signed token is the trusted account reference; the plain fields are
            # for human/debug readability only (client-tamperable).
            "account_token": sign_account(billable_type, billable_id),
            "billable_type": billable_type,
            "billable_id": billable_id,
            "plan_key": plan_key,
            "interval": interval,
        }
        return CheckoutResult(
            mode=CheckoutResult.MODE_CLIENT,
            context={
                "price_id": price_id,
                "paddle_client_token": getattr(settings, "PADDLE_CLIENT_TOKEN", ""),
                "paddle_environment": getattr(settings, "PADDLE_ENVIRONMENT", "sandbox"),
                "customer_email": customer_email,
                "custom_data_json": json.dumps(custom_data),
                "success_url": success_url,
            },
        )

    def create_portal_session(self, *, customer_id, return_url=None):
        if not customer_id:
            return None
        try:
            resp = requests.post(
                f"{api_base()}/customers/{customer_id}/portal-sessions",
                headers=self._headers(),
                json={},
                timeout=_TIMEOUT,
            )
            if resp.status_code >= 400:
                logger.error(
                    "paddle_portal_session_failed",
                    status_code=resp.status_code,
                    body=resp.text[:500],
                )
                return None
            data = resp.json().get("data", {})
            urls = data.get("urls", {}).get("general", {})
            return urls.get("overview")
        except requests.RequestException as exc:
            logger.error("paddle_portal_session_error", error=str(exc))
            return None

    # -- Webhooks ---------------------------------------------------------

    def verify_and_parse_webhook(self, request):
        signature = request.headers.get("Paddle-Signature", "")
        if not verify_webhook_signature(request.body, signature):
            return None
        try:
            return json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def get_event_id(self, event):
        return event.get("event_id") or ""

    def get_event_type(self, event):
        return event.get("event_type") or ""

    def process_event(self, event):
        event_type = event.get("event_type", "")
        if not event_type.startswith("subscription."):
            # Only subscription lifecycle events affect local billing state.
            return
        data = event.get("data", {}) or {}
        normalized = self._normalize_subscription(data, event)
        webhooks.apply_subscription_update(self.provider, normalized)

    def _normalize_subscription(self, data, raw_event):
        custom_data = data.get("custom_data") or {}
        price_id, product_id = self._first_price(data)
        # The granted plan is resolved ONLY from a registry-recognised provider
        # price. Paddle checkout is client-side, so custom_data (and even the
        # priceId) are user-controllable — never trust custom_data.plan_key to
        # grant a paid tier. An unknown price yields plan_key=None and fails
        # closed in apply_subscription_update. interval is non-granting, so a
        # custom_data fallback for it is harmless.
        plan_key, interval = get_plan_for_provider_price_id(self.provider, price_id)
        if not interval:
            interval = custom_data.get("interval") or None

        # The billable account is resolved from the server-signed token only;
        # the plain custom_data fields are not trusted (client-tamperable).
        billable_type, billable_id = unsign_account(custom_data.get("account_token"))

        raw_status = data.get("status", "")
        period = data.get("current_billing_period") or {}
        occurred_at = raw_event.get("occurred_at")

        return {
            "billable_type": billable_type,
            "billable_id": billable_id,
            "event_occurred_at": parse_datetime(occurred_at) if occurred_at else None,
            "provider_subscription_id": data.get("id", ""),
            "provider_customer_id": data.get("customer_id", ""),
            "provider_price_id": price_id,
            "provider_product_id": product_id,
            "plan_key": plan_key,
            "interval": interval,
            "status": _PADDLE_STATUS_MAP.get(raw_status),
            "raw_provider_status": raw_status,
            "current_period_starts_at": parse_datetime(period.get("starts_at") or "")
            if period.get("starts_at")
            else None,
            "current_period_ends_at": parse_datetime(period.get("ends_at") or "")
            if period.get("ends_at")
            else None,
            "trial_starts_at": None,
            "trial_ends_at": None,
            "canceled_at": parse_datetime(data.get("canceled_at") or "")
            if data.get("canceled_at")
            else None,
            "cancellation_effective_at": None,
            "raw_payload": raw_event,
        }

    @staticmethod
    def _first_price(data):
        items = data.get("items") or []
        if not items:
            return "", ""
        price = (items[0] or {}).get("price") or {}
        return price.get("id", "") or "", price.get("product_id", "") or ""
