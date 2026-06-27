"""Tests for the Paddle adapter: signature verification, webhook processing,
status mapping, idempotency, and account resolution from custom data."""

import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from mainapp.billing.paddle import PaddleAdapter, verify_webhook_signature
from mainapp.billing.signing import sign_account
from mainapp.models import BillingEventLog, BillingSubscription, Team
from mainapp.subscription_plans import SUBSCRIPTION_PLANS
from mainapp.views.billing import PaddleWebhookView

WEBHOOK_SECRET = "pdl_ntfset_test"


def sign(body: bytes, secret=WEBHOOK_SECRET, ts="1700000000"):
    signed = f"{ts}:{body.decode()}".encode()
    h1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def subscription_event(team, event_type="subscription.updated", status="active",
                       sub_id="sub_1", price_id="pri_pro_m", event_id="evt_1",
                       plan_key="pro", interval="monthly", account_token=None,
                       occurred_at="2026-01-15T00:00:00Z"):
    if account_token is None:
        account_token = sign_account("team", str(team.id))
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "data": {
            "id": sub_id,
            "customer_id": "ctm_1",
            "status": status,
            "items": [{"price": {"id": price_id, "product_id": "pro_x"}}],
            "current_billing_period": {
                "starts_at": "2026-01-01T00:00:00Z",
                "ends_at": "2026-02-01T00:00:00Z",
            },
            "custom_data": {
                "account_token": account_token,
                "billable_type": "team",
                "billable_id": str(team.id),
                "plan_key": plan_key,
                "interval": interval,
            },
        },
    }


@override_settings(PADDLE_WEBHOOK_SECRET=WEBHOOK_SECRET)
class SignatureTests(TestCase):
    def test_valid_signature(self):
        body = b'{"hello":"world"}'
        self.assertTrue(verify_webhook_signature(body, sign(body)))

    def test_invalid_signature(self):
        body = b'{"hello":"world"}'
        self.assertFalse(verify_webhook_signature(body, sign(b'{"tampered":1}')))

    def test_missing_header(self):
        self.assertFalse(verify_webhook_signature(b"{}", ""))

    @override_settings(PADDLE_WEBHOOK_SECRET="")
    def test_no_secret_rejects(self):
        body = b"{}"
        self.assertFalse(verify_webhook_signature(body, sign(body)))


@override_settings(
    SPEEDPY_BILLING_ENABLED=True,
    SPEEDPY_BILLING_PROVIDER="paddle",
    PADDLE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    PADDLE_PRICE_PRO_MONTHLY="pri_pro_m",
)
class WebhookProcessingTests(TestCase):
    def setUp(self):
        # Patch the registry-resolved price id so price->plan resolves.
        SUBSCRIPTION_PLANS["pro"]["provider_prices"]["paddle"]["monthly"] = "pri_pro_m"
        self.addCleanup(
            lambda: SUBSCRIPTION_PLANS["pro"]["provider_prices"]["paddle"].__setitem__(
                "monthly", ""
            )
        )
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        self.adapter = PaddleAdapter()

    def test_active_event_creates_subscription_and_sets_plan(self):
        self.adapter.process_event(subscription_event(self.team))
        sub = BillingSubscription.objects.get(provider="paddle", provider_subscription_id="sub_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_ACTIVE)
        self.assertEqual(sub.plan_key, "pro")
        self.assertEqual(sub.billable_type, "team")
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "pro")
        self.assertEqual(self.team.limits_max_team_members, 10)

    def test_idempotent_on_repeat(self):
        evt = subscription_event(self.team)
        self.adapter.process_event(evt)
        self.adapter.process_event(evt)
        self.assertEqual(
            BillingSubscription.objects.filter(provider_subscription_id="sub_1").count(), 1
        )

    def test_unknown_status_does_not_grant(self):
        self.adapter.process_event(
            subscription_event(self.team, status="something_weird")
        )
        self.assertFalse(BillingSubscription.objects.exists())
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")

    def test_unknown_price_does_not_grant_even_with_custom_data_plan(self):
        # Client-controllable custom_data.plan_key must NOT grant a paid tier when
        # the price id is not in the registry (fail closed).
        evt = subscription_event(
            self.team, status="active", price_id="pri_TAMPERED", plan_key="business"
        )
        self.adapter.process_event(evt)
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_1")
        # A row is recorded (visible in admin) but with no granted plan.
        self.assertEqual(sub.plan_key, "")

    def test_trialing_maps_to_active(self):
        self.adapter.process_event(subscription_event(self.team, status="trialing"))
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_ACTIVE)

    @patch("mainapp.tasks.billing.send_billing_grace_started_email.delay")
    def test_past_due_sets_grace_period(self, mock_delay):
        self.adapter.process_event(subscription_event(self.team, status="past_due"))
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_PAST_DUE)
        self.assertIsNotNone(sub.grace_period_ends_at)
        self.assertIsNotNone(sub.past_due_started_at)
        mock_delay.assert_called_once()

    def test_unresolvable_billable_is_skipped(self):
        # Signed token for a non-existent team -> resolves to None -> skipped.
        evt = subscription_event(
            self.team,
            account_token=sign_account(
                "team", "00000000-0000-0000-0000-000000000000"
            ),
        )
        self.adapter.process_event(evt)
        self.assertFalse(BillingSubscription.objects.exists())

    def test_forged_custom_data_without_valid_token_is_skipped(self):
        # Tampered custom_data (plain fields point at the team) but an invalid
        # token must not resolve the account -> event skipped (fail closed).
        evt = subscription_event(self.team, account_token="not-a-valid-token")
        self.adapter.process_event(evt)
        self.assertFalse(BillingSubscription.objects.exists())

    def test_existing_sub_unknown_price_downgrades(self):
        # Establish an active paid subscription.
        self.adapter.process_event(subscription_event(self.team, status="active"))
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "pro")
        # A later active update with an unrecognised price must fail closed.
        self.adapter.process_event(
            subscription_event(
                self.team, status="active", price_id="pri_DRIFTED",
                event_id="evt_drift", occurred_at="2026-03-01T00:00:00Z",
            )
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_1")
        self.assertEqual(sub.plan_key, "")

    def test_stale_event_does_not_regrant(self):
        # A later "canceled" then an older "active" must NOT re-grant access.
        self.adapter.process_event(
            subscription_event(
                self.team, status="canceled", event_id="evt_cancel",
                occurred_at="2026-02-01T00:00:00Z",
            )
        )
        self.adapter.process_event(
            subscription_event(
                self.team, status="active", event_id="evt_old",
                occurred_at="2026-01-01T00:00:00Z",
            )
        )
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_CANCELED)

    def test_canceled_records_period_end(self):
        self.adapter.process_event(subscription_event(self.team, status="active"))
        self.adapter.process_event(
            subscription_event(self.team, status="canceled", event_id="evt_2")
        )
        sub = BillingSubscription.objects.get(provider_subscription_id="sub_1")
        self.assertEqual(sub.status, BillingSubscription.STATUS_CANCELED)
        self.assertIsNotNone(sub.current_period_ends_at)


@override_settings(
    SPEEDPY_BILLING_ENABLED=True,
    SPEEDPY_BILLING_PROVIDER="paddle",
    PADDLE_WEBHOOK_SECRET=WEBHOOK_SECRET,
)
class WebhookViewTests(TestCase):
    """Exercise the webhook view directly (RequestFactory), since the billing
    URLs are only registered when SPEEDPY_BILLING_ENABLED is true at import."""

    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        self.view = PaddleWebhookView.as_view()
        self.factory = RequestFactory()

    def _post(self, body, signature):
        request = self.factory.post(
            "/billing/webhooks/paddle/",
            data=body,
            content_type="application/json",
            HTTP_PADDLE_SIGNATURE=signature,
        )
        return self.view(request)

    def test_valid_webhook_returns_200_and_dedupes(self):
        evt = subscription_event(self.team, status="active")
        body = json.dumps(evt).encode()
        resp = self._post(body, sign(body))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BillingEventLog.objects.filter(provider="paddle").count(), 1)
        # Replay -> still 200, still one event log row.
        resp2 = self._post(body, sign(body))
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(BillingEventLog.objects.filter(provider="paddle").count(), 1)

    def test_bad_signature_returns_403(self):
        evt = subscription_event(self.team)
        body = json.dumps(evt).encode()
        resp = self._post(body, "ts=1;h1=deadbeef")
        self.assertEqual(resp.status_code, 403)
