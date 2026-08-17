"""Post-checkout activation: reconcile-on-return + polling status endpoint.

Paddle redirects the browser the instant payment succeeds, while its webhook is a
separate server call that lands afterwards (or, rarely, never). These tests cover
the two layers that stop the customer from seeing their old plan: reconciling from
the provider's own API on return, and the status endpoint the page polls.
"""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from mainapp.models import BillingSubscription, Team, TeamMembership
from mainapp.subscription_plans import SUBSCRIPTION_PLANS
from mainapp.tests.test_billing_views import BillingURLConfMixin
from usermodel.models import User

PRICE_ID = "pri_pro_monthly_test"


def _normalized(billable_type, billable_id, status="active", plan_key="pro"):
    """The provider-neutral dict an adapter returns from fetch_subscription_state."""
    return {
        "billable_type": billable_type,
        "billable_id": str(billable_id),
        "event_occurred_at": None,
        "provider_subscription_id": "sub_test_1",
        "provider_customer_id": "ctm_test_1",
        "provider_price_id": PRICE_ID,
        "provider_product_id": "pro_test_1",
        "plan_key": plan_key,
        "interval": "monthly",
        "status": status,
        "raw_provider_status": "active",
        "current_period_starts_at": None,
        "current_period_ends_at": None,
        "trial_starts_at": None,
        "trial_ends_at": None,
        "canceled_at": None,
        "cancellation_effective_at": None,
        "raw_payload": {"source": "reconcile"},
    }


@override_settings(SPEEDPY_BILLING_ENABLED=True, SPEEDPY_BILLING_PROVIDER="paddle")
class ActivationEndpointTests(BillingURLConfMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw")
        self.member = User.objects.create_user(email="member@example.com", password="pw")
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

        # A second tenant, to prove one cannot drive the other's provisioning.
        self.other_owner = User.objects.create_user(email="other@example.com", password="pw")
        self.other_team = Team.objects.create(name="Other", slug="other", plan="free")
        TeamMembership.objects.create(
            team=self.other_team, user=self.other_owner, role="owner"
        )

    def _url(self, team=None):
        return reverse(
            "team_billing_activation", kwargs={"team_id": (team or self.team).id}
        )

    # -- Status (GET) -----------------------------------------------------

    def test_status_reports_free_plan_before_activation(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["plan_key"], "free")
        self.assertFalse(data["has_active_subscription"])
        self.assertFalse(data["is_paid"])

    def test_status_reports_paid_plan_once_active(self):
        BillingSubscription.objects.create(
            provider="paddle",
            provider_subscription_id="sub_test_1",
            billable_type="team",
            billable_id=str(self.team.id),
            plan_key="pro",
            status=BillingSubscription.STATUS_ACTIVE,
        )
        self.team.plan = "pro"
        self.team.save(update_fields=["plan"])

        self.client.force_login(self.owner)
        data = self.client.get(self._url()).json()
        self.assertEqual(data["plan_key"], "pro")
        self.assertTrue(data["has_active_subscription"])
        self.assertTrue(data["is_paid"])

    def test_status_is_owner_only(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_status_requires_login(self):
        resp = self.client.get(self._url())
        self.assertIn(resp.status_code, (302, 403))

    def test_outsider_gets_404_not_403(self):
        """Non-membership must not confirm the team exists."""
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    # -- Reconcile (POST) -------------------------------------------------

    @patch("mainapp.billing.registry.get_adapter")
    def test_reconcile_activates_the_plan_immediately(self, mock_get_adapter):
        SUBSCRIPTION_PLANS["pro"]["provider_prices"]["paddle"]["monthly"] = PRICE_ID
        self.addCleanup(
            lambda: SUBSCRIPTION_PLANS["pro"]["provider_prices"]["paddle"].__setitem__(
                "monthly", ""
            )
        )
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        adapter.fetch_subscription_state.return_value = _normalized("team", self.team.id)

        self.client.force_login(self.owner)
        resp = self.client.post(self._url(), {"transaction_id": "txn_01hxyz123abc"})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["reconciled"])
        self.assertEqual(data["plan_key"], "pro")
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "pro")

    @patch("mainapp.billing.registry.get_adapter")
    def test_reconcile_is_idempotent_with_the_webhook(self, mock_get_adapter):
        """The webhook may land first, or twice; reconciling must not duplicate
        the subscription row or change the outcome."""
        SUBSCRIPTION_PLANS["pro"]["provider_prices"]["paddle"]["monthly"] = PRICE_ID
        self.addCleanup(
            lambda: SUBSCRIPTION_PLANS["pro"]["provider_prices"]["paddle"].__setitem__(
                "monthly", ""
            )
        )
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        adapter.fetch_subscription_state.return_value = _normalized("team", self.team.id)

        self.client.force_login(self.owner)
        for _ in range(3):
            resp = self.client.post(self._url(), {"transaction_id": "txn_01hxyz123abc"})
            self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            BillingSubscription.objects.filter(
                provider="paddle", provider_subscription_id="sub_test_1"
            ).count(),
            1,
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "pro")

    @patch("mainapp.billing.registry.get_adapter")
    def test_cross_tenant_transaction_is_refused_and_applies_nothing(
        self, mock_get_adapter
    ):
        """The billable comes from the provider's signed custom data, so posting
        another tenant's transaction id must 404 *before* anything is applied."""
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        adapter.fetch_subscription_state.return_value = _normalized(
            "team", self.other_team.id
        )

        self.client.force_login(self.owner)
        resp = self.client.post(self._url(), {"transaction_id": "txn_01hxyz123abc"})

        self.assertEqual(resp.status_code, 404)
        self.team.refresh_from_db()
        self.other_team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")
        self.assertEqual(self.other_team.plan, "free")
        self.assertFalse(BillingSubscription.objects.exists())

    @patch("mainapp.billing.registry.get_adapter")
    def test_malformed_transaction_id_is_rejected_without_calling_the_provider(
        self, mock_get_adapter
    ):
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        self.client.force_login(self.owner)

        for bad in ("", "short", "txn_" + "a" * 90, "txn_abc/../x", "txn abc"):
            with self.subTest(bad=bad):
                resp = self.client.post(self._url(), {"transaction_id": bad})
                self.assertEqual(resp.status_code, 400)
                self.assertFalse(resp.json()["reconciled"])
        adapter.fetch_subscription_state.assert_not_called()

    @patch("mainapp.billing.registry.get_adapter")
    def test_unknown_provider_state_falls_back_to_polling(self, mock_get_adapter):
        """When the provider cannot tell us yet, answer 200 with reconciled=False
        so the page polls rather than showing a dead end."""
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        adapter.fetch_subscription_state.return_value = None

        self.client.force_login(self.owner)
        resp = self.client.post(self._url(), {"transaction_id": "txn_01hxyz123abc"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["reconciled"])
        self.assertEqual(data["plan_key"], "free")

    @patch("mainapp.billing.registry.get_adapter")
    def test_reconcile_is_owner_only(self, mock_get_adapter):
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        self.client.force_login(self.member)
        resp = self.client.post(self._url(), {"transaction_id": "txn_01hxyz123abc"})
        self.assertEqual(resp.status_code, 403)
        adapter.fetch_subscription_state.assert_not_called()

    @patch("mainapp.billing.registry.get_adapter")
    def test_unknown_price_does_not_grant_a_paid_plan(self, mock_get_adapter):
        """Same fail-closed rule as the webhook: a price absent from the registry
        must never grant a tier, even though custom_data names one."""
        adapter = mock_get_adapter.return_value
        adapter.provider = "paddle"
        adapter.fetch_subscription_state.return_value = _normalized(
            "team", self.team.id, plan_key=None
        )

        self.client.force_login(self.owner)
        resp = self.client.post(self._url(), {"transaction_id": "txn_01hxyz123abc"})
        self.assertEqual(resp.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")


@override_settings(SPEEDPY_BILLING_ENABLED=True, SPEEDPY_BILLING_PROVIDER="paddle")
class ActivatingBannerTests(BillingURLConfMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw")
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        self.client.force_login(self.owner)

    def _url(self):
        return reverse("team_billing", kwargs={"team_id": self.team.id})

    def test_banner_and_poller_render_while_activating(self):
        body = self.client.get(self._url(), {"activating": "1"}).content.decode()
        self.assertIn("activation-pending", body)
        self.assertIn("We are activating your", body)
        self.assertIn(
            reverse("team_billing_activation", kwargs={"team_id": self.team.id}), body
        )

    def test_no_banner_without_the_flag(self):
        body = self.client.get(self._url()).content.decode()
        self.assertNotIn("activation-pending", body)

    def test_banner_suppressed_once_the_subscription_is_active(self):
        """A stale ?activating=1 bookmark must not claim a live plan is pending."""
        BillingSubscription.objects.create(
            provider="paddle",
            provider_subscription_id="sub_test_1",
            billable_type="team",
            billable_id=str(self.team.id),
            plan_key="pro",
            status=BillingSubscription.STATUS_ACTIVE,
        )
        body = self.client.get(self._url(), {"activating": "1"}).content.decode()
        self.assertNotIn("activation-pending", body)
