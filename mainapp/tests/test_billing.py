"""Tests for the plan registry, runtime billing state, gating, and plan application."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from mainapp.billing import plans, state
from mainapp.models import BillingSubscription, Team, TeamMembership
from mainapp.subscription_plans import (
    DEFAULT_PLAN_KEY,
    SUBSCRIPTION_PLANS,
    SUBSCRIPTION_PLANS_CHOICES,
    get_plan_config,
    get_plan_for_provider_price_id,
    get_plan_limit,
    get_provider_price_id,
    plan_has_feature,
)
from usermodel.models import User


def make_sub(billable_type, billable_id, **kwargs):
    defaults = dict(
        provider="stripe",
        provider_subscription_id=f"sub_{billable_id}",
        plan_key="pro",
        status=BillingSubscription.STATUS_ACTIVE,
    )
    defaults.update(kwargs)
    return BillingSubscription.objects.create(
        billable_type=billable_type, billable_id=str(billable_id), **defaults
    )


class PlanRegistryTests(TestCase):
    def test_choices_cover_all_plans(self):
        keys = {k for k, _ in SUBSCRIPTION_PLANS_CHOICES}
        self.assertEqual(keys, {"free", "pro", "business", "enterprise"})

    def test_get_plan_config_falls_back_to_free(self):
        self.assertEqual(get_plan_config("nonexistent")["key"], "free")

    def test_free_plan_not_paid(self):
        self.assertFalse(get_plan_config("free")["is_paid"])

    def test_enterprise_is_contact(self):
        self.assertTrue(get_plan_config("enterprise")["is_contact"])

    def test_provider_price_resolution_roundtrip(self):
        # Price IDs come from settings/env at import; here we set the registry
        # value directly (and restore it) to exercise the resolver round-trip.
        SUBSCRIPTION_PLANS["pro"]["provider_prices"]["stripe"]["monthly"] = "price_abc"
        self.addCleanup(
            lambda: SUBSCRIPTION_PLANS["pro"]["provider_prices"]["stripe"].__setitem__(
                "monthly", ""
            )
        )
        self.assertEqual(get_provider_price_id("stripe", "pro", "monthly"), "price_abc")
        self.assertEqual(
            get_plan_for_provider_price_id("stripe", "price_abc"), ("pro", "monthly")
        )

    def test_unknown_price_id_fails_closed(self):
        self.assertEqual(
            get_plan_for_provider_price_id("stripe", "price_unknown"), (None, None)
        )
        self.assertEqual(get_plan_for_provider_price_id("stripe", ""), (None, None))

    def test_missing_price_id_is_empty_string(self):
        # No env configured in tests -> empty, never raises.
        self.assertEqual(get_provider_price_id("paddle", "pro", "yearly"), "")

    def test_plan_helpers(self):
        self.assertEqual(get_plan_limit("pro", "max_team_members"), 10)
        self.assertIsNone(get_plan_limit("enterprise", "max_team_members"))
        self.assertTrue(plan_has_feature("pro", "Priority email support"))


class TeamPlanConfigTests(TestCase):
    def test_team_get_plan_config_delegates(self):
        team = Team.objects.create(name="T", slug="t", plan="pro")
        self.assertEqual(team.get_plan_config()["key"], "pro")

    def test_team_unknown_plan_falls_back(self):
        team = Team.objects.create(name="T", slug="t", plan="ghost")
        self.assertEqual(team.get_plan_config()["key"], "free")


class BillingStateTeamTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme", plan="pro")

    def _bid(self):
        return str(self.team.id)

    def test_free_team_enabled(self):
        self.team.plan = "free"
        self.team.save()
        self.assertEqual(state.get_billing_state(self.team), state.ENABLED)

    def test_paid_without_subscription_disabled(self):
        self.assertEqual(state.get_billing_state(self.team), state.DISABLED)

    def test_active_subscription_enabled(self):
        make_sub("team", self.team.id, status=BillingSubscription.STATUS_ACTIVE)
        self.assertEqual(state.get_billing_state(self.team), state.ENABLED)

    def test_past_due_within_grace_is_grace(self):
        make_sub(
            "team",
            self.team.id,
            status=BillingSubscription.STATUS_PAST_DUE,
            grace_period_ends_at=timezone.now() + timedelta(days=5),
        )
        self.assertEqual(state.get_billing_state(self.team), state.GRACE)
        self.assertFalse(state.can_create_records(self.team))

    def test_past_due_after_grace_disabled(self):
        make_sub(
            "team",
            self.team.id,
            status=BillingSubscription.STATUS_PAST_DUE,
            grace_period_ends_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(state.get_billing_state(self.team), state.DISABLED)

    def test_canceled_within_period_enabled(self):
        make_sub(
            "team",
            self.team.id,
            status=BillingSubscription.STATUS_CANCELED,
            current_period_ends_at=timezone.now() + timedelta(days=3),
        )
        self.assertEqual(state.get_billing_state(self.team), state.ENABLED)

    def test_canceled_after_period_disabled(self):
        make_sub(
            "team",
            self.team.id,
            status=BillingSubscription.STATUS_CANCELED,
            current_period_ends_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(state.get_billing_state(self.team), state.DISABLED)

    def test_feature_gate_fails_closed_when_disabled(self):
        # Paid plan, no subscription -> disabled -> paid feature denied.
        self.assertFalse(
            state.account_has_feature(self.team, "Priority email support")
        )


class BillingStateUserTests(TestCase):
    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_user_billable_resolution(self):
        user = User.objects.create_user(email="u@example.com", password="pw")
        self.assertEqual(state.get_billable_for_user(user), user)

    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_user_effective_plan_from_subscription(self):
        user = User.objects.create_user(email="u2@example.com", password="pw")
        make_sub("user", user.id, status=BillingSubscription.STATUS_ACTIVE, plan_key="business")
        self.assertEqual(state.effective_plan_key(user), "business")
        self.assertEqual(state.get_billing_state(user), state.ENABLED)

    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_user_canceled_within_period_keeps_plan(self):
        user = User.objects.create_user(email="u4@example.com", password="pw")
        make_sub(
            "user",
            user.id,
            status=BillingSubscription.STATUS_CANCELED,
            plan_key="pro",
            current_period_ends_at=timezone.now() + timedelta(days=3),
        )
        # billing_state ENABLED until period end -> effective plan must stay paid.
        self.assertEqual(state.get_billing_state(user), state.ENABLED)
        self.assertEqual(state.effective_plan_key(user), "pro")

    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_user_canceled_after_period_is_free(self):
        user = User.objects.create_user(email="u5@example.com", password="pw")
        make_sub(
            "user",
            user.id,
            status=BillingSubscription.STATUS_CANCELED,
            plan_key="pro",
            current_period_ends_at=timezone.now() - timedelta(days=1),
        )
        # In user mode the effective plan is derived live, so a lapsed sub drops
        # straight to free (ENABLED, because free is always enabled — no paid
        # plan left to disable). Paid access is gone.
        self.assertEqual(state.effective_plan_key(user), DEFAULT_PLAN_KEY)
        self.assertFalse(state.account_has_feature(user, "Priority email support"))

    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_user_no_subscription_is_free(self):
        user = User.objects.create_user(email="u3@example.com", password="pw")
        self.assertEqual(state.effective_plan_key(user), DEFAULT_PLAN_KEY)
        self.assertEqual(state.get_billing_state(user), state.ENABLED)


class PlanApplicationTests(TestCase):
    def test_apply_plan_syncs_team_limits(self):
        team = Team.objects.create(name="T", slug="t", plan="free")
        plans.apply_plan_to_billable(team, "business")
        team.refresh_from_db()
        self.assertEqual(team.plan, "business")
        self.assertEqual(team.limits_max_team_members, 25)

    def test_downgrade_to_free(self):
        team = Team.objects.create(name="T", slug="t", plan="pro")
        plans.downgrade_to_free(team)
        team.refresh_from_db()
        self.assertEqual(team.plan, "free")
        self.assertEqual(team.limits_max_team_members, 3)


class PeriodicTaskTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme", plan="pro")

    @patch("mainapp.tasks.billing.send_billing_disabled_email.delay")
    def test_past_due_beyond_grace_downgrades_and_expires(self, mock_delay):
        from mainapp.tasks.billing import process_billing_subscriptions

        sub = make_sub(
            "team",
            self.team.id,
            status=BillingSubscription.STATUS_PAST_DUE,
            grace_period_ends_at=timezone.now() - timedelta(days=1),
        )
        process_billing_subscriptions()
        sub.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(sub.status, BillingSubscription.STATUS_EXPIRED)
        self.assertEqual(self.team.plan, "free")
        mock_delay.assert_called_once()

    def test_canceled_past_period_downgrades(self):
        from mainapp.tasks.billing import process_billing_subscriptions

        make_sub(
            "team",
            self.team.id,
            status=BillingSubscription.STATUS_CANCELED,
            current_period_ends_at=timezone.now() - timedelta(days=1),
        )
        process_billing_subscriptions()
        self.team.refresh_from_db()
        self.assertEqual(self.team.plan, "free")


class OverLimitTests(TestCase):
    def test_over_limit_report_for_team(self):
        team = Team.objects.create(name="T", slug="t", plan="free")
        # free allows 3 members; add 4.
        for i in range(4):
            u = User.objects.create_user(email=f"m{i}@example.com", password="pw")
            TeamMembership.objects.create(team=team, user=u, role="member")
        report = state.over_limit_report(team)
        self.assertIn("team_members", report)
        self.assertEqual(report["team_members"]["limit"], 3)
        self.assertEqual(report["team_members"]["count"], 4)
