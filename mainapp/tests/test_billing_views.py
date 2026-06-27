"""Tests for billing views: owner-only permissions, team vs user modes, and
checkout/portal guard behaviour.

The billing URLs are only registered when SPEEDPY_BILLING_ENABLED is true at
import, so each test class reloads the URLconf under the override and restores it
afterwards (see ``BillingURLConfMixin``).
"""

from importlib import reload
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import clear_url_caches

from mainapp.billing.base import CheckoutResult
from mainapp.models import BillingSubscription, Team, TeamMembership
from mainapp.subscription_plans import SUBSCRIPTION_PLANS
from usermodel.models import User


def _reload_urls():
    import mainapp.urls
    import project.urls

    reload(mainapp.urls)
    reload(project.urls)
    clear_url_caches()


class BillingURLConfMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()  # enables class-level override_settings
        _reload_urls()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()  # disables override_settings
        _reload_urls()  # restore billing-disabled URLconf


@override_settings(SPEEDPY_BILLING_ENABLED=True, SPEEDPY_BILLING_PROVIDER="stripe")
class TeamBillingPermissionTests(BillingURLConfMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw")
        self.admin = User.objects.create_user(email="admin@example.com", password="pw")
        self.member = User.objects.create_user(email="member@example.com", password="pw")
        self.outsider = User.objects.create_user(email="out@example.com", password="pw")
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        TeamMembership.objects.create(team=self.team, user=self.admin, role="admin")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

    def _url(self):
        return f"/teams/{self.team.id}/billing/"

    def test_owner_can_view(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_admin_denied(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_member_denied(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_outsider_404(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_unknown_team_404(self):
        self.client.force_login(self.owner)
        resp = self.client.get("/teams/00000000-0000-0000-0000-000000000000/billing/")
        self.assertEqual(resp.status_code, 404)


@override_settings(SPEEDPY_BILLING_ENABLED=True, SPEEDPY_BILLING_PROVIDER="stripe")
class TeamCheckoutGuardTests(BillingURLConfMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw")
        self.team = Team.objects.create(name="Acme", slug="acme", plan="free")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        self.client.force_login(self.owner)

    def _checkout(self, plan_key, interval="monthly"):
        return self.client.get(
            f"/teams/{self.team.id}/billing/checkout/{plan_key}/{interval}/"
        )

    def test_unknown_plan_404(self):
        self.assertEqual(self._checkout("ghost").status_code, 404)

    def test_contact_plan_404(self):
        self.assertEqual(self._checkout("enterprise").status_code, 404)

    def test_active_subscription_redirects_to_overview(self):
        BillingSubscription.objects.create(
            billable_type="team",
            billable_id=str(self.team.id),
            provider="stripe",
            provider_subscription_id="sub_1",
            plan_key="pro",
            status=BillingSubscription.STATUS_ACTIVE,
        )
        resp = self._checkout("pro")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("billing", resp.url)

    def test_missing_price_id_redirects(self):
        # No Stripe price configured for 'pro' -> cannot checkout, redirect.
        resp = self._checkout("pro")
        self.assertEqual(resp.status_code, 302)

    @patch("mainapp.billing.registry.get_adapter")
    def test_happy_path_redirects_to_checkout_url(self, mock_get_adapter):
        SUBSCRIPTION_PLANS["pro"]["provider_prices"]["stripe"]["monthly"] = "price_pro_m"
        self.addCleanup(
            lambda: SUBSCRIPTION_PLANS["pro"]["provider_prices"]["stripe"].__setitem__(
                "monthly", ""
            )
        )
        mock_adapter = mock_get_adapter.return_value
        mock_adapter.create_checkout.return_value = CheckoutResult(
            mode=CheckoutResult.MODE_REDIRECT, url="https://stripe.test/checkout"
        )
        resp = self._checkout("pro")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "https://stripe.test/checkout")
        _, kwargs = mock_adapter.create_checkout.call_args
        self.assertEqual(kwargs["billable_type"], "team")
        self.assertEqual(kwargs["billable_id"], str(self.team.id))


@override_settings(
    SPEEDPY_BILLING_ENABLED=True,
    SPEEDPY_BILLING_PROVIDER="stripe",
    SPEEDPY_TEAMS_ENABLED=False,
)
class AccountBillingModeTests(BillingURLConfMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="pw")

    def test_account_billing_renders_in_user_mode(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/accounts/billing/").status_code, 200)
