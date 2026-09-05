"""Tests for the Stripe adapter: status mapping, subscription normalization,
webhook signature handling, and account resolution from metadata.

Stripe Python v15 stopped subclassing ``dict`` and moved the billing period onto
subscription items. These tests exercise both the plain-dict path (fast unit
tests) and the real SDK-object path (a signed webhook parsed by the actual SDK),
so a future SDK behaviour change is caught rather than silently mishandled.
"""

import decimal
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

import stripe
from django.test import TestCase, override_settings

from mainapp.billing.signing import sign_account
from mainapp.billing.stripe import StripeAdapter, _to_plain
from mainapp.models import BillingEventLog, BillingSubscription, Team
from mainapp.subscription_plans import SUBSCRIPTION_PLANS

_PERIOD_START = 1735689600  # 2025-01-01 UTC
_PERIOD_END = 1738368000  # 2025-02-01 UTC


def stripe_subscription(team, status="active", sub_id="sub_stripe_1",
                        price_id="price_pro_m", plan_key="pro", interval="monthly",
                        legacy_period=False):
    """A Stripe subscription payload.

    By default the billing period lives on the subscription *item*, matching the
    real API since 2025-03-31.basil. ``legacy_period=True`` places it at the
    subscription top level instead, to exercise the fallback for older webhook
    endpoints.
    """
    item = {"price": {"id": price_id, "product": "prod_1"}}
    sub = {
        "id": sub_id,
        "customer": "cus_1",
        "status": status,
        "items": {"data": [item]},
        "metadata": {
            "account_token": sign_account("team", str(team.id)),
            "billable_type": "team",
            "billable_id": str(team.id),
            "plan_key": plan_key,
            "interval": interval,
        },
    }
    if legacy_period:
        sub["current_period_start"] = _PERIOD_START
        sub["current_period_end"] = _PERIOD_END
    else:
        item["current_period_start"] = _PERIOD_START
        item["current_period_end"] = _PERIOD_END
    return sub


@override_settings(
    SPEEDPY_BILLING_ENABLED=True,
    SPEEDPY_BILLING_PROVIDER="stripe",
    STRIPE_SECRET_KEY="sk_test",
    STRIPE_WEBHOOK_SECRET="whsec_test",
)
class StripeWebhookProcessingTests(TestCase):
    def setUp(self):
        SUBSCRIPTION_PLANS["pro"]["provider_prices"]["stripe"]["monthly"] = "price_pro_m"
        self.addCleanup(
            lambda: SUBSCRIPTION_PLANS["pro"]["provider_prices"]["stripe"].__setitem__(
                "monthly", ""
            )
        )
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        self.adapter = StripeAdapter()

    def _event(self, sub, event_type="customer.subscription.updated"):
        return {"id": "evt_x", "type": event_type, "data": {"object": sub}}

    def test_active_subscription_sets_plan(self):
        self.adapter.process_event(self._event(stripe_subscription(self.team)))
        sub = BillingSubscription.objects.get(provider="stripe", provider_subscription_id="sub_stripe_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_ACTIVE)
        self.assertEqual(sub.plan_key, "pro")
        self.assertEqual(sub.billable_type, "team")
        # Period comes from the subscription item (basil+ API shape).
        self.assertEqual(
            sub.current_period_starts_at,
            datetime.fromtimestamp(_PERIOD_START, tz=dt_timezone.utc),
        )
        self.assertEqual(
            sub.current_period_ends_at,
            datetime.fromtimestamp(_PERIOD_END, tz=dt_timezone.utc),
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "pro")

    def test_period_falls_back_to_subscription_level(self):
        # Legacy webhook endpoints (older API version) still put the period at
        # the subscription top level; the adapter must fall back to it.
        self.adapter.process_event(
            self._event(stripe_subscription(self.team, legacy_period=True))
        )
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_stripe_1")
        self.assertEqual(
            sub.current_period_ends_at,
            datetime.fromtimestamp(_PERIOD_END, tz=dt_timezone.utc),
        )

    def test_unpaid_maps_to_expired_and_downgrades(self):
        self.team.plan = "pro"
        self.team.save()
        self.adapter.process_event(self._event(stripe_subscription(self.team, status="unpaid")))
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_stripe_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_EXPIRED)
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")

    def test_incomplete_status_ignored(self):
        self.adapter.process_event(self._event(stripe_subscription(self.team, status="incomplete")))
        self.assertFalse(BillingSubscription.objects.exists())

    def test_idempotent(self):
        evt = self._event(stripe_subscription(self.team))
        self.adapter.process_event(evt)
        self.adapter.process_event(evt)
        self.assertEqual(
            BillingSubscription.objects.filter(provider_subscription_id="sub_stripe_1").count(), 1
        )

    @patch("mainapp.billing.stripe.stripe.Subscription.retrieve")
    def test_checkout_completed_retrieves_subscription(self, mock_retrieve):
        # Return a real v15 SDK object (not a dict) to prove the retrieve ->
        # _to_plain() boundary handles a StripeObject.
        mock_retrieve.return_value = stripe.Subscription.construct_from(
            stripe_subscription(self.team), "sk_test"
        )
        event = {
            "id": "evt_co",
            "type": "checkout.session.completed",
            "data": {"object": {"subscription": "sub_stripe_1", "metadata": {}}},
        }
        self.adapter.process_event(event)
        mock_retrieve.assert_called_once_with("sub_stripe_1")
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_stripe_1")
        self.assertEqual(sub.plan_key, "pro")
        self.assertEqual(
            sub.current_period_ends_at,
            datetime.fromtimestamp(_PERIOD_END, tz=dt_timezone.utc),
        )

    def test_webhook_verify_requires_secret_and_signature(self):
        from django.test import RequestFactory

        request = RequestFactory().post("/x", data=b"{}", content_type="application/json")
        # No Stripe-Signature header -> None.
        self.assertIsNone(self.adapter.verify_and_parse_webhook(request))

    @patch("mainapp.billing.stripe.stripe.Webhook.construct_event")
    def test_webhook_verify_parses_valid(self, mock_construct):
        from django.test import RequestFactory

        mock_construct.return_value = {"id": "evt_1", "type": "ping"}
        request = RequestFactory().post(
            "/x", data=b"{}", content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=abc",
        )
        event = self.adapter.verify_and_parse_webhook(request)
        self.assertEqual(event["id"], "evt_1")

    def test_signed_webhook_end_to_end_through_the_view(self):
        """A real signed payload, parsed by the actual v15 SDK, through the view.

        Proves the full path: signature verification -> StripeObject ->
        _to_plain(for_json=True) -> dict access -> persistence. Includes a
        ``unit_amount_decimal`` so the JSONField write proves Decimal coercion.

        Calls the view directly (RequestFactory): the billing URLs are included
        conditionally at import time on ``SPEEDPY_BILLING_ENABLED``, so
        ``reverse()`` cannot see them under ``override_settings``.
        """
        from django.test import RequestFactory

        from mainapp.views.billing import StripeWebhookView

        payload = self._event(stripe_subscription(self.team))
        payload["id"] = "evt_signed_1"
        payload["created"] = _PERIOD_START
        # A decimal_string field the v15 SDK may deserialize to Decimal.
        payload["data"]["object"]["items"]["data"][0]["price"]["unit_amount_decimal"] = "1000"

        body = json.dumps(payload).encode()
        ts = int(time.time())
        signature = hmac.new(
            b"whsec_test", f"{ts}.".encode() + body, hashlib.sha256
        ).hexdigest()
        header = f"t={ts},v1={signature}"

        request = RequestFactory().post(
            "/billing/webhooks/stripe/",
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=header,
        )
        resp = StripeWebhookView.as_view()(request)
        self.assertEqual(resp.status_code, 200)

        sub = BillingSubscription.objects.get(provider_subscription_id="sub_stripe_1")
        self.assertEqual(sub.plan_key, "pro")
        self.assertEqual(
            sub.current_period_ends_at,
            datetime.fromtimestamp(_PERIOD_END, tz=dt_timezone.utc),
        )
        # The event log stored a JSON-serializable payload.
        log = BillingEventLog.objects.get(provider="stripe", event_id="evt_signed_1")
        self.assertEqual(log.event_type, "customer.subscription.updated")
        json.dumps(log.payload)  # must not raise


class ToPlainHelperTests(TestCase):
    def test_to_plain_passes_through_plain_dict(self):
        d = {"a": 1, "nested": {"b": 2}}
        self.assertEqual(_to_plain(d), d)

    def test_to_plain_flattens_stripe_object(self):
        obj = stripe.Subscription.construct_from(
            {"id": "sub_1", "items": {"data": [{"price": {"id": "p_1"}}]}},
            "sk_test",
        )
        plain = _to_plain(obj)
        self.assertIsInstance(plain, dict)
        self.assertEqual(plain["items"]["data"][0]["price"]["id"], "p_1")

    def test_to_plain_for_json_coerces_decimal(self):
        obj = stripe.Subscription.construct_from(
            {"id": "sub_1", "items": {"data": [
                {"price": {"unit_amount_decimal": decimal.Decimal("1000.5")}}
            ]}},
            "sk_test",
        )
        plain = _to_plain(obj, for_json=True)
        value = plain["items"]["data"][0]["price"]["unit_amount_decimal"]
        self.assertEqual(value, "1000.5")
        json.dumps(plain)  # must not raise
