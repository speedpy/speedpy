"""Tests for the Stripe adapter: status mapping, subscription normalization,
webhook signature handling, and account resolution from metadata."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from mainapp.billing.signing import sign_account
from mainapp.billing.stripe import StripeAdapter
from mainapp.models import BillingSubscription, Team
from mainapp.subscription_plans import SUBSCRIPTION_PLANS


def stripe_subscription(team, status="active", sub_id="sub_stripe_1",
                        price_id="price_pro_m", plan_key="pro", interval="monthly"):
    return {
        "id": sub_id,
        "customer": "cus_1",
        "status": status,
        "items": {"data": [{"price": {"id": price_id, "product": "prod_1"}}]},
        "current_period_start": 1735689600,  # 2025-01-01
        "current_period_end": 1738368000,  # 2025-02-01
        "metadata": {
            "account_token": sign_account("team", str(team.id)),
            "billable_type": "team",
            "billable_id": str(team.id),
            "plan_key": plan_key,
            "interval": interval,
        },
    }


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
        self.assertIsNotNone(sub.current_period_ends_at)
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "pro")

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
        mock_retrieve.return_value = stripe_subscription(self.team)
        event = {
            "id": "evt_co",
            "type": "checkout.session.completed",
            "data": {"object": {"subscription": "sub_stripe_1", "metadata": {}}},
        }
        self.adapter.process_event(event)
        mock_retrieve.assert_called_once_with("sub_stripe_1")
        self.assertTrue(
            BillingSubscription.objects.filter(provider_subscription_id="sub_stripe_1").exists()
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
