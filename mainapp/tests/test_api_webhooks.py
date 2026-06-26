import secrets
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application
from rest_framework.test import APIClient

from mainapp.models import Team, TeamMembership
from mainapp.models.webhooks import WebhookDelivery, WebhookEndpoint
from mainapp.webhooks.events import WebhookEvent
from usermodel.models import User


class WebhookAPITestBase(TestCase):
    """Shared setup for webhook API tests."""

    def setUp(self):
        self.client = APIClient()

        # Users
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pass123"
        )
        self.admin = User.objects.create_user(
            email="admin@example.com", password="pass123"
        )
        self.member = User.objects.create_user(
            email="member@example.com", password="pass123"
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", password="pass123"
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com", password="pass123"
        )

        # Team A
        self.team_a = Team.objects.create(name="Team A", slug="team-a")
        TeamMembership.objects.create(team=self.team_a, user=self.owner, role="owner")
        TeamMembership.objects.create(team=self.team_a, user=self.admin, role="admin")
        TeamMembership.objects.create(team=self.team_a, user=self.member, role="member")
        TeamMembership.objects.create(team=self.team_a, user=self.viewer, role="viewer")

        # Team B (outsider owns it)
        self.team_b = Team.objects.create(name="Team B", slug="team-b")
        TeamMembership.objects.create(team=self.team_b, user=self.outsider, role="owner")

        # A webhook endpoint in team A
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team_a,
            name="Test Hook",
            url="https://example.com/webhook",
            events=[WebhookEvent.TEAM_MEMBER_ADDED],
        )

        # OAuth2 app for scope tests
        self.oauth_app = Application.objects.create(
            name="Test App",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            user=self.owner,
            redirect_uris="https://example.com/callback",
            client_secret=secrets.token_urlsafe(32),
        )

    def _create_token(self, user, scope="read:webhooks write:webhooks"):
        return AccessToken.objects.create(
            user=user,
            application=self.oauth_app,
            token=secrets.token_hex(32),
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
        )

    def _team_url(self, suffix=""):
        return f"/api/v1/teams/{self.team_a.id}/webhooks/{suffix}"

    def _endpoint_url(self, endpoint=None, suffix=""):
        ep = endpoint or self.endpoint
        return f"/api/v1/teams/{self.team_a.id}/webhooks/{ep.id}/{suffix}"


# ---------------------------------------------------------------------------
# Auth & Scope tests
# ---------------------------------------------------------------------------

class WebhookScopeTests(WebhookAPITestBase):
    def test_anonymous_rejected(self):
        response = self.client.get(self._team_url())
        self.assertIn(response.status_code, [401, 403])

    def test_no_webhook_scope_denied_on_list(self):
        token = self._create_token(self.owner, scope="read:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get(self._team_url())
        self.assertIn(response.status_code, [401, 403])

    def test_read_scope_allows_list(self):
        token = self._create_token(self.owner, scope="read:webhooks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get(self._team_url())
        self.assertEqual(response.status_code, 200)

    def test_read_scope_denies_create(self):
        token = self._create_token(self.owner, scope="read:webhooks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/new", "events": [WebhookEvent.TEAM_MEMBER_ADDED]},
            format="json",
        )
        self.assertIn(response.status_code, [401, 403])

    def test_write_scope_allows_create(self):
        token = self._create_token(self.owner, scope="write:webhooks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/new", "events": [WebhookEvent.TEAM_MEMBER_ADDED]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_no_scope_denied_on_get_detail(self):
        token = self._create_token(self.owner, scope="read:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get(self._endpoint_url())
        self.assertIn(response.status_code, [401, 403])

    def test_read_scope_denies_delete(self):
        token = self._create_token(self.owner, scope="read:webhooks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.delete(self._endpoint_url())
        self.assertIn(response.status_code, [401, 403])

    def test_read_scope_denies_rotate_secret(self):
        token = self._create_token(self.owner, scope="read:webhooks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        self.assertIn(response.status_code, [401, 403])

    def test_user_scoped_list_requires_read_scope(self):
        token = self._create_token(self.owner, scope="read:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/webhooks/")
        self.assertIn(response.status_code, [401, 403])


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------

class WebhookCRUDTests(WebhookAPITestBase):
    def test_create_endpoint(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {
                "name": "My Hook",
                "url": "https://hooks.example.com/receive",
                "events": [WebhookEvent.TEAM_MEMBER_ADDED, WebhookEvent.TEAM_INVITATION_CREATED],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("signing_secret", response.data)
        self.assertTrue(len(response.data["signing_secret"]) > 10)
        self.assertEqual(response.data["name"], "My Hook")
        self.assertEqual(response.data["url"], "https://hooks.example.com/receive")
        self.assertTrue(response.data["is_active"])

    def test_create_endpoint_without_name(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "")

    def test_list_endpoints(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._team_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.endpoint.id))

    def test_get_endpoint_detail(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._endpoint_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Test Hook")
        # Secret should NOT be in GET response
        self.assertNotIn("signing_secret", response.data)

    def test_secret_not_in_list(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._team_url())
        self.assertNotIn("signing_secret", response.data["results"][0])
        self.assertNotIn("secret", response.data["results"][0])

    def test_update_endpoint_put(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.put(
            self._endpoint_url(),
            {
                "name": "Updated Hook",
                "url": "https://new.example.com/hook",
                "events": [WebhookEvent.USER_PROFILE_UPDATED],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Updated Hook")
        self.assertEqual(response.data["url"], "https://new.example.com/hook")

    def test_update_endpoint_patch(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            self._endpoint_url(),
            {"name": "Patched"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Patched")
        # URL unchanged
        self.assertEqual(response.data["url"], "https://example.com/webhook")

    def test_soft_delete_endpoint(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self._endpoint_url())
        self.assertEqual(response.status_code, 204)

        self.endpoint.refresh_from_db()
        self.assertFalse(self.endpoint.is_active)
        self.assertEqual(self.endpoint.events, [])

    def test_list_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._team_url())
        expected = {"id", "name", "url", "events", "is_active", "created_at", "updated_at"}
        self.assertEqual(set(response.data["results"][0].keys()), expected)

    def test_list_is_paginated(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._team_url())
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)

    def test_create_response_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/new", "events": ["*"]},
            format="json",
        )
        expected = {"id", "name", "url", "events", "is_active", "created_at", "updated_at", "signing_secret"}
        self.assertEqual(set(response.data.keys()), expected)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

class WebhookTenantIsolationTests(WebhookAPITestBase):
    def test_outsider_cannot_list_team_a_webhooks(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(self._team_url())
        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_get_team_a_endpoint(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(self._endpoint_url())
        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_create_in_team_a(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            self._team_url(),
            {"url": "https://evil.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_delete_team_a_endpoint(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.delete(self._endpoint_url())
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_team_returns_404(self):
        self.client.force_authenticate(user=self.owner)
        fake_team = uuid.uuid4()
        response = self.client.get(f"/api/v1/teams/{fake_team}/webhooks/")
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_endpoint_returns_404(self):
        self.client.force_authenticate(user=self.owner)
        fake_endpoint = uuid.uuid4()
        response = self.client.get(
            f"/api/v1/teams/{self.team_a.id}/webhooks/{fake_endpoint}/"
        )
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------

class WebhookRoleTests(WebhookAPITestBase):
    def test_viewer_can_read(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._team_url())
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_create(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_update(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.patch(
            self._endpoint_url(),
            {"name": "Hacked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_delete(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.delete(self._endpoint_url())
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_rotate_secret(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        self.assertEqual(response.status_code, 403)

    def test_member_can_create(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_admin_can_update(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            self._endpoint_url(),
            {"name": "Admin Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class WebhookValidationTests(WebhookAPITestBase):
    def test_http_url_rejected(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {"url": "http://insecure.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_event_type_rejected(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/hook", "events": ["bogus.event"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_empty_events_rejected(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/hook", "events": []},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_wildcard_event_accepted(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._team_url(),
            {"url": "https://example.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["events"], ["*"])

    def test_unknown_event_on_update_rejected(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            self._endpoint_url(),
            {"events": ["not.real"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# Rotate secret
# ---------------------------------------------------------------------------

class WebhookRotateSecretTests(WebhookAPITestBase):
    def test_rotate_secret_returns_new_secret(self):
        self.client.force_authenticate(user=self.owner)
        old_secret = self.endpoint.secret

        response = self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("signing_secret", response.data)
        self.assertNotEqual(response.data["signing_secret"], old_secret)

        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.secret, response.data["signing_secret"])

    def test_rotate_secret_returns_rotation_metadata(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("secret_rotated_at", response.data)
        self.assertIn("previous_secret_expires_at", response.data)
        self.assertIn("rotation_overlap_seconds", response.data)
        self.assertEqual(response.data["rotation_overlap_seconds"], 86400)

    def test_rotate_secret_stores_previous_secret(self):
        self.client.force_authenticate(user=self.owner)
        old_secret = self.endpoint.secret

        self.client.post(self._endpoint_url(suffix="rotate-secret/"))

        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.previous_secret, old_secret)
        self.assertIsNotNone(self.endpoint.secret_rotated_at)
        self.assertIsNotNone(self.endpoint.previous_secret_expires_at)

    def test_rotate_secret_repeated_replaces_previous(self):
        self.client.force_authenticate(user=self.owner)
        original_secret = self.endpoint.secret

        self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        self.endpoint.refresh_from_db()
        second_secret = self.endpoint.secret

        self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        self.endpoint.refresh_from_db()
        # previous_secret should be second_secret, not original
        self.assertEqual(self.endpoint.previous_secret, second_secret)
        self.assertNotEqual(self.endpoint.previous_secret, original_secret)

    def test_rotate_secret_response_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(self._endpoint_url(suffix="rotate-secret/"))
        expected = {
            "id", "name", "url", "events", "is_active", "created_at", "updated_at",
            "signing_secret", "secret_rotated_at", "previous_secret_expires_at",
            "rotation_overlap_seconds",
        }
        self.assertEqual(set(response.data.keys()), expected)


# ---------------------------------------------------------------------------
# Test delivery
# ---------------------------------------------------------------------------

class WebhookTestDeliveryTests(WebhookAPITestBase):
    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_test_delivery_creates_delivery(self, mock_delay):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix="test/"),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("payload", response.data)
        self.assertTrue(response.data["payload"]["data"]["test"])
        self.assertEqual(response.data["event_type"], WebhookEvent.TEAM_MEMBER_ADDED)

        delivery = WebhookDelivery.objects.get(pk=response.data["id"])
        self.assertEqual(delivery.endpoint, self.endpoint)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_test_delivery_with_explicit_event_type(self, mock_delay):
        # Endpoint subscribes to wildcard
        self.endpoint.events = ["*"]
        self.endpoint.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix="test/"),
            {"event_type": WebhookEvent.USER_PROFILE_UPDATED},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["event_type"], WebhookEvent.USER_PROFILE_UPDATED)

    def test_test_delivery_inactive_endpoint_rejected(self):
        self.endpoint.is_active = False
        self.endpoint.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix="test/"),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_test_delivery_event_not_subscribed_rejected(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix="test/"),
            {"event_type": WebhookEvent.USER_PROFILE_UPDATED},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_test_delivery_unknown_event_on_wildcard_rejected(self):
        self.endpoint.events = ["*"]
        self.endpoint.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix="test/"),
            {"event_type": "totally.bogus.event"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_test_delivery(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(
            self._endpoint_url(suffix="test/"),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Delivery list & detail
# ---------------------------------------------------------------------------

class WebhookDeliveryTests(WebhookAPITestBase):
    def setUp(self):
        super().setUp()
        self.delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_id="evt_test123",
            event_type=WebhookEvent.TEAM_MEMBER_ADDED,
            payload={"event_id": "evt_test123", "event_type": "team.member.added", "data": {}},
            status=WebhookDelivery.Status.SUCCESS,
            http_status_code=200,
        )

    def test_list_deliveries(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._endpoint_url(suffix="deliveries/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_get_delivery_detail(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(
            self._endpoint_url(suffix=f"deliveries/{self.delivery.pk}/")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("payload", response.data)
        self.assertIn("response_body", response.data)

    def test_delivery_list_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._endpoint_url(suffix="deliveries/"))
        item = response.data["results"][0]
        expected = {
            "id", "event_id", "event_type", "status", "http_status_code",
            "attempts", "created_at", "delivered_at", "error_message",
        }
        self.assertEqual(set(item.keys()), expected)

    def test_delivery_detail_includes_payload(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(
            self._endpoint_url(suffix=f"deliveries/{self.delivery.pk}/")
        )
        self.assertIn("payload", response.data)
        self.assertIn("response_body", response.data)

    def test_outsider_cannot_list_deliveries(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(self._endpoint_url(suffix="deliveries/"))
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_delivery_returns_404(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._endpoint_url(suffix="deliveries/99999/"))
        self.assertEqual(response.status_code, 404)

    def test_deliveries_scoped_to_endpoint(self):
        """Delivery from endpoint B should not appear in endpoint A's list."""
        other_endpoint = WebhookEndpoint.objects.create(
            team=self.team_a,
            url="https://other.example.com/hook",
            events=["*"],
        )
        WebhookDelivery.objects.create(
            endpoint=other_endpoint,
            event_id="evt_other",
            event_type="team.member.added",
            payload={"data": {}},
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self._endpoint_url(suffix="deliveries/"))
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["event_id"], "evt_test123")


# ---------------------------------------------------------------------------
# Delivery retry
# ---------------------------------------------------------------------------

class WebhookDeliveryRetryTests(WebhookAPITestBase):
    def setUp(self):
        super().setUp()
        self.failed_delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_id="evt_fail",
            event_type=WebhookEvent.TEAM_MEMBER_ADDED,
            payload={"data": {}},
            status=WebhookDelivery.Status.FAILED,
            attempts=5,
            error_message="HTTP 500 (exhausted 8 retries)",
        )

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_retry_failed_delivery(self, mock_delay):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix=f"deliveries/{self.failed_delivery.pk}/retry/")
        )
        self.assertEqual(response.status_code, 200)

        self.failed_delivery.refresh_from_db()
        self.assertEqual(self.failed_delivery.status, WebhookDelivery.Status.PENDING)
        self.assertEqual(self.failed_delivery.attempts, 0)
        self.assertEqual(self.failed_delivery.error_message, "")

    def test_retry_success_delivery_rejected(self):
        self.failed_delivery.status = WebhookDelivery.Status.SUCCESS
        self.failed_delivery.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix=f"deliveries/{self.failed_delivery.pk}/retry/")
        )
        self.assertEqual(response.status_code, 400)

    def test_retry_pending_delivery_rejected(self):
        self.failed_delivery.status = WebhookDelivery.Status.PENDING
        self.failed_delivery.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix=f"deliveries/{self.failed_delivery.pk}/retry/")
        )
        self.assertEqual(response.status_code, 400)

    def test_retry_in_flight_delivery_rejected(self):
        self.failed_delivery.status = WebhookDelivery.Status.IN_FLIGHT
        self.failed_delivery.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self._endpoint_url(suffix=f"deliveries/{self.failed_delivery.pk}/retry/")
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_retry(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(
            self._endpoint_url(suffix=f"deliveries/{self.failed_delivery.pk}/retry/")
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# User-scoped list
# ---------------------------------------------------------------------------

class UserWebhookListTests(WebhookAPITestBase):
    def test_user_sees_endpoints_from_all_teams(self):
        # Give owner membership in team B too
        TeamMembership.objects.create(team=self.team_b, user=self.owner, role="member")
        WebhookEndpoint.objects.create(
            team=self.team_b,
            url="https://teamb.example.com/hook",
            events=["*"],
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/v1/webhooks/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)

    def test_user_does_not_see_other_teams(self):
        # outsider has team B only, not A
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get("/api/v1/webhooks/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 0)

    def test_user_scoped_list_is_read_only(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/v1/webhooks/",
            {"url": "https://example.com/hook", "events": ["*"]},
            format="json",
        )
        self.assertIn(response.status_code, [405])


# ---------------------------------------------------------------------------
# OpenAPI schema
# ---------------------------------------------------------------------------

@override_settings(API_DOCS_PUBLIC=True)
class WebhookSchemaTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_schema_includes_webhook_operations(self):
        response = self.client.get("/api/schema/")
        content = str(response.content)
        self.assertIn("listTeamWebhookEndpoints", content)
        self.assertIn("createTeamWebhookEndpoint", content)
        self.assertIn("getTeamWebhookEndpoint", content)
        self.assertIn("updateTeamWebhookEndpoint", content)
        self.assertIn("deleteTeamWebhookEndpoint", content)
        self.assertIn("rotateTeamWebhookEndpointSecret", content)
        self.assertIn("testTeamWebhookEndpoint", content)
        self.assertIn("listTeamWebhookDeliveries", content)
        self.assertIn("getTeamWebhookDelivery", content)
        self.assertIn("retryTeamWebhookDelivery", content)
        self.assertIn("listUserWebhookEndpoints", content)
        self.assertIn("webhooks", content)
