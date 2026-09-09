"""Tests for the webhook lifecycle hardening (gating, ownership, deactivation,
retention). Generic behaviour only — a downstream project layers its own plan
feature onto the ``SPEEDPY_WEBHOOK_TEAM_ELIGIBLE`` seam.
"""

import secrets
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, RefreshToken
from rest_framework.test import APIClient

from mainapp.models import Team, TeamMembership
from mainapp.models.webhooks import WebhookDelivery, WebhookEndpoint
from mainapp.webhooks import lifecycle
from mainapp.webhooks.dispatch import dispatch_event
from mainapp.webhooks.events import WebhookEvent
from mainapp.tasks.webhooks import (
    deliver_webhook,
    purge_deliveries,
    reconcile_endpoints,
)
from usermodel.models import User


# Module-level eligibility fakes referenced by dotted path in override_settings.
_INELIGIBLE_TEAM_IDS = set()


def only_eligible_teams(team):
    return team.id not in _INELIGIBLE_TEAM_IDS


def never_eligible(team):
    return False


@override_settings(SPEEDPY_WEBHOOK_TEAM_ELIGIBLE=None)
class LifecycleTestBase(TestCase):
    # Baseline: no plan-feature gate. Tests that exercise the gate override the
    # seam per-method with a fake (a downstream project that wires the seam
    # globally must not turn these generic tests into 403s/skips).
    def setUp(self):
        self.client = APIClient()
        lifecycle.reset_team_eligible_cache()
        _INELIGIBLE_TEAM_IDS.clear()

        self.owner = User.objects.create_user(email="owner@example.com", password="pass123")
        self.member = User.objects.create_user(email="member@example.com", password="pass123")
        self.team = Team.objects.create(name="Team A", slug="team-a")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

        self.app = Application.objects.create(
            name="Test App",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            user=self.owner,
            redirect_uris="https://example.com/callback",
            client_secret=secrets.token_urlsafe(32),
        )

    def tearDown(self):
        lifecycle.reset_team_eligible_cache()
        _INELIGIBLE_TEAM_IDS.clear()

    def _oauth_token(self, user, scope="read:webhooks write:webhooks", with_refresh=True):
        at = AccessToken.objects.create(
            user=user,
            application=self.app,
            token=secrets.token_hex(32),
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
        )
        family = None
        if with_refresh:
            family = uuid.uuid4()
            RefreshToken.objects.create(
                user=user,
                application=self.app,
                token=secrets.token_hex(32),
                access_token=at,
                token_family=family,
            )
        return at, family

    def _team_url(self, suffix=""):
        return f"/api/v1/teams/{self.team.id}/webhooks/{suffix}"


# ---------------------------------------------------------------------------
# §5.1 — the feature/billing gate
# ---------------------------------------------------------------------------

class FeatureGateTests(LifecycleTestBase):
    def _post_create(self):
        return self.client.post(
            self._team_url(),
            {"url": "https://hooks.example.com/x", "events": ["*"]},
            format="json",
        )

    def test_no_seam_allows_token_create(self):
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        self.assertEqual(self._post_create().status_code, 201)

    @override_settings(
        SPEEDPY_WEBHOOK_TEAM_ELIGIBLE="mainapp.tests.test_webhook_lifecycle.only_eligible_teams",
        SPEEDPY_WEBHOOK_FEATURE_DENIED_DETAIL="Upgrade required.",
    )
    def test_ineligible_team_token_create_denied(self):
        _INELIGIBLE_TEAM_IDS.add(self.team.id)
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        resp = self._post_create()
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Upgrade required", str(resp.data))

    @override_settings(
        SPEEDPY_WEBHOOK_TEAM_ELIGIBLE="mainapp.tests.test_webhook_lifecycle.never_eligible",
    )
    def test_ineligible_team_session_create_bypasses(self):
        # Session (browser) users bypass the plan gate.
        self.client.force_login(self.owner)
        self.assertEqual(self._post_create().status_code, 201)

    @override_settings(
        SPEEDPY_WEBHOOK_TEAM_ELIGIBLE="mainapp.tests.test_webhook_lifecycle.only_eligible_teams",
    )
    def test_ineligible_team_token_read_denied(self):
        _INELIGIBLE_TEAM_IDS.add(self.team.id)
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        self.assertEqual(self.client.get(self._team_url()).status_code, 403)

    @patch("mainapp.billing.state.get_billing_state")
    @patch("mainapp.billing.state.is_billing_enabled", return_value=True)
    def test_billing_blocked_402_on_create_but_204_on_delete(self, _en, _state):
        from mainapp.billing.state import GRACE

        _state.return_value = GRACE
        endpoint = WebhookEndpoint.objects.create(
            team=self.team, url="https://hooks.example.com/y", events=["*"]
        )
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")

        create = self._post_create()
        self.assertEqual(create.status_code, 402)

        delete = self.client.delete(self._team_url(f"{endpoint.id}/"))
        self.assertEqual(delete.status_code, 204)


class EndpointCapTests(LifecycleTestBase):
    @override_settings(WEBHOOK_MAX_ACTIVE_ENDPOINTS_PER_TEAM=2)
    def test_cap_enforced_on_create(self):
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    self._team_url(),
                    {"url": "https://hooks.example.com/x", "events": ["*"]},
                    format="json",
                ).status_code,
                201,
            )
        resp = self.client.post(
            self._team_url(),
            {"url": "https://hooks.example.com/x", "events": ["*"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limit", str(resp.data).lower())


# ---------------------------------------------------------------------------
# §5.2 — origin capture and dispatch lifecycle
# ---------------------------------------------------------------------------

class OriginCaptureTests(LifecycleTestBase):
    def test_session_create_is_dashboard_origin(self):
        self.client.force_login(self.owner)
        self.client.post(
            self._team_url(),
            {"url": "https://hooks.example.com/x", "events": ["*"]},
            format="json",
        )
        ep = WebhookEndpoint.objects.get(team=self.team)
        self.assertEqual(ep.origin, WebhookEndpoint.Origin.DASHBOARD)
        self.assertEqual(ep.created_by_id, self.owner.id)
        self.assertIsNone(ep.application_id)

    def test_oauth_create_captures_application_and_family(self):
        at, family = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        self.client.post(
            self._team_url(),
            {"url": "https://hooks.example.com/x", "events": ["*"]},
            format="json",
        )
        ep = WebhookEndpoint.objects.get(team=self.team)
        self.assertEqual(ep.origin, WebhookEndpoint.Origin.OAUTH)
        self.assertEqual(ep.application_id, self.app.id)
        self.assertEqual(ep.token_family, family)
        self.assertEqual(ep.created_by_id, self.owner.id)

    def test_oauth_without_refresh_downgrades_to_api_token(self):
        # An OAuth access token with no paired refresh token cannot supply a
        # connection identity → api_token (membership-gated), not a dead oauth row.
        at, _ = self._oauth_token(self.owner, with_refresh=False)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        self.client.post(
            self._team_url(),
            {"url": "https://hooks.example.com/x", "events": ["*"]},
            format="json",
        )
        ep = WebhookEndpoint.objects.get(team=self.team)
        self.assertEqual(ep.origin, WebhookEndpoint.Origin.API_TOKEN)
        self.assertIsNone(ep.token_family)
        self.assertEqual(ep.created_by_id, self.owner.id)
        # It delivers (creator is a member), rather than being permanently dead.
        self.assertEqual(len(dispatch_event(self.team, WebhookEvent.TEAM_MEMBER_ADDED, {})), 1)


class DispatchLifecycleTests(LifecycleTestBase):
    def _dispatch(self):
        return dispatch_event(self.team, WebhookEvent.TEAM_MEMBER_ADDED, {"x": 1})

    def test_dashboard_endpoint_delivers(self):
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.DASHBOARD, created_by=self.owner,
        )
        self.assertEqual(len(self._dispatch()), 1)

    def test_oauth_endpoint_with_live_family_delivers(self):
        at, family = self._oauth_token(self.member)
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.OAUTH, created_by=self.member,
            application=self.app, token_family=family,
        )
        self.assertEqual(len(self._dispatch()), 1)

    def test_oauth_endpoint_with_revoked_family_skipped(self):
        at, family = self._oauth_token(self.member)
        RefreshToken.objects.filter(token_family=family).update(revoked=timezone.now())
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.OAUTH, created_by=self.member,
            application=self.app, token_family=family,
        )
        self.assertEqual(self._dispatch(), [])

    def test_null_token_family_fails_closed(self):
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.OAUTH, created_by=self.member,
            application=self.app, token_family=None,
        )
        self.assertEqual(self._dispatch(), [])

    def test_creator_removed_from_team_skipped(self):
        at, family = self._oauth_token(self.member)
        ep = WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.OAUTH, created_by=self.member,
            application=self.app, token_family=family,
        )
        TeamMembership.objects.filter(team=self.team, user=self.member).delete()
        self.assertEqual(self._dispatch(), [])

    def test_null_creator_fails_closed(self):
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.API_TOKEN, created_by=None,
        )
        self.assertEqual(self._dispatch(), [])

    def test_unknown_origin_fails_closed(self):
        # choices is not a DB constraint; an invalid/future origin must not be
        # treated like dashboard/legacy and delivered.
        ep = WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.DASHBOARD, created_by=self.owner,
        )
        WebhookEndpoint.objects.filter(pk=ep.pk).update(origin="something_new")
        self.assertEqual(self._dispatch(), [])

    @override_settings(
        SPEEDPY_WEBHOOK_TEAM_ELIGIBLE="mainapp.tests.test_webhook_lifecycle.only_eligible_teams",
    )
    def test_ineligible_team_skips_even_dashboard_endpoint(self):
        _INELIGIBLE_TEAM_IDS.add(self.team.id)
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.DASHBOARD, created_by=self.owner,
        )
        self.assertEqual(self._dispatch(), [])

    def test_legacy_origin_grandfathered_delivers(self):
        # A pre-connection-identity row (null creator) is grandfathered: rule 1
        # only, so it still delivers while the team is eligible.
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.LEGACY, created_by=None,
        )
        self.assertEqual(len(self._dispatch()), 1)

    @override_settings(
        SPEEDPY_WEBHOOK_TEAM_ELIGIBLE="mainapp.tests.test_webhook_lifecycle.only_eligible_teams",
    )
    def test_legacy_origin_skipped_when_team_ineligible(self):
        _INELIGIBLE_TEAM_IDS.add(self.team.id)
        WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.LEGACY, created_by=None,
        )
        self.assertEqual(self._dispatch(), [])


class ReconcileTests(LifecycleTestBase):
    def test_reconcile_deactivates_failing_and_is_idempotent(self):
        # A revoked-family OAuth endpoint should be deactivated by reconcile.
        at, family = self._oauth_token(self.member)
        RefreshToken.objects.filter(token_family=family).update(revoked=timezone.now())
        ep = WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.OAUTH, created_by=self.member,
            application=self.app, token_family=family,
        )
        # A healthy dashboard endpoint should be left alone.
        good = WebhookEndpoint.objects.create(
            team=self.team, url="https://h/ok", events=["*"],
            origin=WebhookEndpoint.Origin.DASHBOARD, created_by=self.owner,
        )
        result = reconcile_endpoints()
        self.assertEqual(result["deactivated"], 1)
        ep.refresh_from_db()
        good.refresh_from_db()
        self.assertFalse(ep.is_active)
        self.assertTrue(good.is_active)
        # Idempotent: a second run flips nothing.
        self.assertEqual(reconcile_endpoints()["deactivated"], 0)


# ---------------------------------------------------------------------------
# §5.4 — one deactivation path; 410 CAS
# ---------------------------------------------------------------------------

class DeactivationCASTests(LifecycleTestBase):
    def _endpoint(self, url="https://sub.example.com/hook"):
        return WebhookEndpoint.objects.create(
            team=self.team, url=url, events=["*"],
            origin=WebhookEndpoint.Origin.DASHBOARD, created_by=self.owner,
        )

    def _deliver_with_status(self, delivery, status_code):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = ""
        client = MagicMock()
        client.__enter__.return_value.post.return_value = resp
        with patch("mainapp.tasks.webhooks.httpx.Client", return_value=client):
            deliver_webhook(delivery.pk)

    def test_410_deactivates_endpoint(self):
        ep = self._endpoint()
        delivery = WebhookDelivery.objects.create(
            endpoint=ep, event_id="evt_1", event_type=WebhookEvent.TEAM_MEMBER_ADDED,
            payload={"event_id": "evt_1"},
        )
        self._deliver_with_status(delivery, 410)
        ep.refresh_from_db()
        delivery.refresh_from_db()
        self.assertFalse(ep.is_active)
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
        self.assertIn("410", delivery.error_message)

    def test_cas_url_mismatch_is_noop(self):
        # A stale 410 carries the URL it POSTed to; if the endpoint was
        # re-pointed since, the compare-and-set must not deactivate it.
        ep = self._endpoint(url="https://new.example.com/hook")
        flipped = lifecycle.deactivate_endpoint(
            ep, reason="stale_410", expected_url="https://old.example.com/hook"
        )
        ep.refresh_from_db()
        self.assertFalse(flipped)
        self.assertTrue(ep.is_active)

    def test_410_during_concurrent_repoint_does_not_deactivate(self):
        # Simulate a PATCH repointing the URL *during* the HTTP call: the task
        # POSTed to the old URL and carries it as expected_url, but the row now
        # holds the new URL, so the CAS finds nothing to flip.
        ep = self._endpoint(url="https://old.example.com/hook")
        delivery = WebhookDelivery.objects.create(
            endpoint=ep, event_id="evt_1", event_type=WebhookEvent.TEAM_MEMBER_ADDED,
            payload={"event_id": "evt_1"},
        )
        resp = MagicMock(status_code=410, text="")

        def _post_then_repoint(*a, **k):
            WebhookEndpoint.objects.filter(pk=ep.pk).update(url="https://new.example.com/hook")
            return resp

        client = MagicMock()
        client.__enter__.return_value.post.side_effect = _post_then_repoint
        with patch("mainapp.tasks.webhooks.httpx.Client", return_value=client):
            deliver_webhook(delivery.pk)
        ep.refresh_from_db()
        self.assertTrue(ep.is_active)

    def test_patch_cannot_set_is_active(self):
        # is_active is not an updatable field: a PATCH cannot resurrect a
        # deactivated endpoint (which would bypass CAS, cap and billing).
        ep = self._endpoint()
        lifecycle.deactivate_endpoint(ep, reason="test")
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        resp = self.client.patch(
            self._team_url(f"{ep.id}/"),
            {"is_active": True, "events": ["*"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        ep.refresh_from_db()
        self.assertFalse(ep.is_active)

    def test_patch_does_not_reactivate_after_cas_deactivation(self):
        ep = self._endpoint()
        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        # Simulate the reverse race: the row is deactivated after the view would
        # have loaded it, then a PATCH of an unrelated field is applied.
        lifecycle.deactivate_endpoint(ep, reason="test")
        resp = self.client.patch(
            self._team_url(f"{ep.id}/"), {"name": "renamed"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        ep.refresh_from_db()
        self.assertFalse(ep.is_active)
        self.assertEqual(ep.name, "renamed")


# ---------------------------------------------------------------------------
# §5.5 — retention purge
# ---------------------------------------------------------------------------

class PurgeTests(LifecycleTestBase):
    def _endpoint(self):
        return WebhookEndpoint.objects.create(
            team=self.team, url="https://h/x", events=["*"],
            origin=WebhookEndpoint.Origin.DASHBOARD, created_by=self.owner,
        )

    def _delivery(self, age_days, status=WebhookDelivery.Status.SUCCESS):
        d = WebhookDelivery.objects.create(
            endpoint=self._endpoint(), event_id=f"evt_{age_days}",
            event_type=WebhookEvent.TEAM_MEMBER_ADDED,
            payload={"data": {"answer": "secret text"}},
            response_body="body", status=status, error_message="line1\nline2",
        )
        WebhookDelivery.objects.filter(pk=d.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        d.refresh_from_db()
        return d

    @override_settings(WEBHOOK_DELIVERY_RETENTION_DAYS=30, WEBHOOK_DELIVERY_DELETE_DAYS=90)
    def test_redacts_after_retention_and_deletes_after_delete_window(self):
        fresh = self._delivery(1)
        old = self._delivery(45)
        ancient = self._delivery(120)

        result = purge_deliveries()

        fresh.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual(fresh.status, WebhookDelivery.Status.SUCCESS)
        self.assertEqual(fresh.payload, {"data": {"answer": "secret text"}})
        self.assertEqual(old.status, WebhookDelivery.Status.REDACTED)
        self.assertEqual(old.payload, {"redacted": True, "event_type": WebhookEvent.TEAM_MEMBER_ADDED})
        self.assertEqual(old.response_body, "")
        self.assertEqual(old.error_message, "line1")
        self.assertFalse(WebhookDelivery.objects.filter(pk=ancient.pk).exists())
        # Both old and ancient are redacted (terminal, past retention); the
        # ancient one is then deleted (redacted + past the delete window).
        self.assertEqual(result["redacted"], 2)
        self.assertEqual(result["deleted"], 1)

    @override_settings(WEBHOOK_DELIVERY_RETENTION_DAYS=30, WEBHOOK_DELIVERY_DELETE_DAYS=90)
    def test_retry_of_redacted_delivery_refused(self):
        old = self._delivery(45)
        purge_deliveries()
        old.refresh_from_db()
        self.assertEqual(old.status, WebhookDelivery.Status.REDACTED)

        at, _ = self._oauth_token(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {at.token}")
        resp = self.client.post(
            self._team_url(f"{old.endpoint_id}/deliveries/{old.pk}/retry/")
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data.get("code"), "delivery_redacted")
