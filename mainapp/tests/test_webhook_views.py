from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch

from mainapp.models import Team, TeamMembership
from mainapp.models.webhooks import WebhookEndpoint, WebhookDelivery

User = get_user_model()


class WebhookViewTestBase(TestCase):
    """Shared setup for webhook view tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="testpass123"
        )
        self.team = Team.objects.create(name="Test Team", slug="test-team")
        self.membership = TeamMembership.objects.create(
            team=self.team, user=self.user, role="owner"
        )
        self.client.login(email="owner@example.com", password="testpass123")

    def _create_endpoint(self, **kwargs):
        defaults = {
            "team": self.team,
            "name": "Test Hook",
            "url": "https://example.com/hook",
            "events": ["team.member.added"],
        }
        defaults.update(kwargs)
        return WebhookEndpoint.objects.create(**defaults)


class TestWebhookListView(WebhookViewTestBase):
    def test_list_empty(self):
        url = reverse("team_webhooks", kwargs={"team_id": self.team.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No webhook endpoints yet.")

    def test_list_with_endpoints(self):
        self._create_endpoint(name="Hook A")
        self._create_endpoint(name="Hook B", is_active=False)
        url = reverse("team_webhooks", kwargs={"team_id": self.team.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Hook A")
        self.assertContains(resp, "Hook B")
        self.assertContains(resp, "Active")
        self.assertContains(resp, "Revoked")

    def test_non_member_gets_404(self):
        other_user = User.objects.create_user(
            email="stranger@example.com", password="testpass123"
        )
        self.client.login(email="stranger@example.com", password="testpass123")
        url = reverse("team_webhooks", kwargs={"team_id": self.team.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_viewer_can_see_list(self):
        viewer = User.objects.create_user(
            email="viewer@example.com", password="testpass123"
        )
        TeamMembership.objects.create(
            team=self.team, user=viewer, role="viewer"
        )
        self.client.login(email="viewer@example.com", password="testpass123")
        self._create_endpoint(name="Visible Hook")
        url = reverse("team_webhooks", kwargs={"team_id": self.team.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Visible Hook")
        self.assertNotContains(resp, "Create webhook")


class TestWebhookCreateView(WebhookViewTestBase):
    def test_create_success(self):
        url = reverse("team_webhook_create", kwargs={"team_id": self.team.pk})
        resp = self.client.post(url, {
            "name": "New Hook",
            "url": "https://example.com/new",
            "events": ["team.member.added"],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(WebhookEndpoint.objects.filter(name="New Hook", team=self.team).exists())

    def test_create_rejects_http(self):
        url = reverse("team_webhook_create", kwargs={"team_id": self.team.pk})
        resp = self.client.post(url, {
            "name": "Bad Hook",
            "url": "http://example.com/insecure",
            "events": ["team.member.added"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(WebhookEndpoint.objects.filter(name="Bad Hook").exists())

    def test_create_wildcard_events(self):
        url = reverse("team_webhook_create", kwargs={"team_id": self.team.pk})
        resp = self.client.post(url, {
            "name": "All Events",
            "url": "https://example.com/all",
            "events": ["*", "team.member.added"],
        })
        self.assertEqual(resp.status_code, 302)
        ep = WebhookEndpoint.objects.get(name="All Events")
        self.assertEqual(ep.events, ["*"])

    def test_viewer_cannot_create(self):
        viewer = User.objects.create_user(
            email="viewer@example.com", password="testpass123"
        )
        TeamMembership.objects.create(
            team=self.team, user=viewer, role="viewer"
        )
        self.client.login(email="viewer@example.com", password="testpass123")
        url = reverse("team_webhook_create", kwargs={"team_id": self.team.pk})
        count_before = WebhookEndpoint.objects.count()
        resp = self.client.post(url, {
            "name": "Blocked",
            "url": "https://example.com/blocked",
            "events": ["team.member.added"],
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(WebhookEndpoint.objects.count(), count_before)

    def test_secret_shown_once(self):
        url = reverse("team_webhook_create", kwargs={"team_id": self.team.pk})
        resp = self.client.post(url, {
            "name": "Secret Hook",
            "url": "https://example.com/secret",
            "events": ["team.member.added"],
        }, follow=True)
        self.assertContains(resp, "Copy")
        # Second visit should not show secret
        list_url = reverse("team_webhooks", kwargs={"team_id": self.team.pk})
        resp2 = self.client.get(list_url)
        self.assertNotContains(resp2, "Copy the signing secret")


class TestWebhookDetailView(WebhookViewTestBase):
    def test_detail_page(self):
        ep = self._create_endpoint()
        url = reverse("team_webhook_detail", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, ep.url)
        self.assertContains(resp, "Configuration")

    def test_detail_shows_deliveries(self):
        ep = self._create_endpoint()
        WebhookDelivery.objects.create(
            endpoint=ep,
            event_id="evt_test1",
            event_type="team.member.added",
            payload={"test": True},
            status="success",
            http_status_code=200,
        )
        url = reverse("team_webhook_detail", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.get(url)
        self.assertContains(resp, "team.member.added")
        self.assertContains(resp, "Success")


class TestWebhookRevokeView(WebhookViewTestBase):
    def test_revoke(self):
        ep = self._create_endpoint()
        url = reverse("team_webhook_revoke", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        ep.refresh_from_db()
        self.assertFalse(ep.is_active)
        self.assertEqual(ep.events, [])

    def test_viewer_cannot_revoke(self):
        viewer = User.objects.create_user(
            email="viewer@example.com", password="testpass123"
        )
        TeamMembership.objects.create(
            team=self.team, user=viewer, role="viewer"
        )
        self.client.login(email="viewer@example.com", password="testpass123")
        ep = self._create_endpoint()
        url = reverse("team_webhook_revoke", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 403)


class TestWebhookTestDeliveryView(WebhookViewTestBase):
    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_test_delivery(self, mock_delay):
        ep = self._create_endpoint()
        url = reverse("team_webhook_test", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(WebhookDelivery.objects.filter(endpoint=ep).exists())

    def test_test_inactive_endpoint(self):
        ep = self._create_endpoint(is_active=False)
        url = reverse("team_webhook_test", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.post(url, follow=True)
        self.assertContains(resp, "Cannot send test delivery to an inactive endpoint.")


class TestWebhookRotateSecretView(WebhookViewTestBase):
    def test_rotate_secret(self):
        ep = self._create_endpoint()
        old_secret = ep.secret
        url = reverse("team_webhook_rotate_secret", kwargs={
            "team_id": self.team.pk, "webhook_id": ep.pk
        })
        resp = self.client.post(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        ep.refresh_from_db()
        self.assertNotEqual(ep.secret, old_secret)
        self.assertContains(resp, "Copy")


class TestCrossTeamIsolation(WebhookViewTestBase):
    def test_cannot_access_other_team_webhooks(self):
        other_team = Team.objects.create(name="Other Team", slug="other-team")
        ep = WebhookEndpoint.objects.create(
            team=other_team,
            url="https://example.com/other",
            events=["*"],
        )
        # User is member of self.team but not other_team
        url = reverse("team_webhooks", kwargs={"team_id": other_team.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_cannot_revoke_other_team_webhook(self):
        other_team = Team.objects.create(name="Other Team", slug="other-team")
        ep = WebhookEndpoint.objects.create(
            team=other_team,
            url="https://example.com/other",
            events=["*"],
        )
        url = reverse("team_webhook_revoke", kwargs={
            "team_id": other_team.pk, "webhook_id": ep.pk
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
