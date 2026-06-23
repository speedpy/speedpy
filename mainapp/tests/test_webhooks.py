from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.test import TestCase

from mainapp.admin.webhooks import WebhookDeliveryAdmin, WebhookEndpointAdmin
from mainapp.models import Team, WebhookDelivery, WebhookEndpoint
from mainapp.webhooks.events import WebhookEvent
from usermodel.models import User


class WebhookEndpointModelTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")

    def test_create_endpoint_generates_secret(self):
        ep = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["team.member.added"],
        )
        self.assertTrue(ep.secret)
        self.assertGreater(len(ep.secret), 20)

    def test_encrypted_secret_round_trip(self):
        ep = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )
        raw_secret = ep.secret
        ep_from_db = WebhookEndpoint.objects.get(pk=ep.pk)
        self.assertEqual(ep_from_db.secret, raw_secret)

    def test_name_is_optional(self):
        ep = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=[],
        )
        self.assertEqual(ep.name, "")

    def test_is_active_defaults_true(self):
        ep = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=[],
        )
        self.assertTrue(ep.is_active)

    def test_subscribes_to_specific_event(self):
        ep = WebhookEndpoint(events=["team.member.added"])
        self.assertTrue(ep.subscribes_to("team.member.added"))
        self.assertFalse(ep.subscribes_to("user.profile.updated"))

    def test_subscribes_to_wildcard(self):
        ep = WebhookEndpoint(events=["*"])
        self.assertTrue(ep.subscribes_to("team.member.added"))
        self.assertTrue(ep.subscribes_to("anything.else"))

    def test_subscribes_to_empty(self):
        ep = WebhookEndpoint(events=[])
        self.assertFalse(ep.subscribes_to("team.member.added"))

    def test_str_with_name(self):
        ep = WebhookEndpoint(
            name="My Hook",
            url="https://example.com/hook",
            team=self.team,
        )
        self.assertIn("My Hook", str(ep))

    def test_str_without_name(self):
        ep = WebhookEndpoint(
            url="https://example.com/hook",
            team=self.team,
        )
        self.assertIn("https://example.com/hook", str(ep))


class WebhookEndpointURLValidationTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")

    def test_https_url_accepted(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )
        ep.full_clean()  # should not raise

    def test_http_url_rejected(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="http://example.com/hook",
            events=["*"],
        )
        with self.assertRaises(ValidationError):
            ep.full_clean()


class WebhookEndpointEventValidationTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")

    def test_known_event_accepted(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events=[WebhookEvent.TEAM_MEMBER_ADDED],
        )
        ep.full_clean()

    def test_wildcard_accepted(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )
        ep.full_clean()

    def test_unknown_event_rejected(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events=["totally.bogus.event"],
        )
        with self.assertRaises(ValidationError):
            ep.full_clean()

    def test_multiple_valid_events(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events=[
                WebhookEvent.TEAM_MEMBER_ADDED,
                WebhookEvent.USER_PROFILE_UPDATED,
            ],
        )
        ep.full_clean()

    def test_non_string_event_rejected(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events=[{"nested": "object"}],
        )
        with self.assertRaises(ValidationError):
            ep.full_clean()

    def test_events_not_a_list_rejected(self):
        ep = WebhookEndpoint(
            team=self.team,
            url="https://example.com/hook",
            events="team.member.added",
        )
        with self.assertRaises(ValidationError):
            ep.full_clean()


class WebhookDeliveryModelTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )

    def test_create_delivery(self):
        d = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_id="evt_abc123",
            event_type="team.member.added",
            payload={"id": "evt_abc123", "type": "team.member.added"},
        )
        self.assertEqual(d.status, WebhookDelivery.Status.PENDING)
        self.assertEqual(d.attempts, 0)
        self.assertIsNone(d.http_status_code)

    def test_delivery_str(self):
        d = WebhookDelivery(
            endpoint=self.endpoint,
            event_type="team.member.added",
            status=WebhookDelivery.Status.SUCCESS,
        )
        s = str(d)
        self.assertIn("team.member.added", s)
        self.assertIn("success", s)

    def test_response_body_stored(self):
        d = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_id="evt_xyz",
            event_type="team.member.added",
            payload={},
            response_body="OK",
            http_status_code=200,
            status=WebhookDelivery.Status.SUCCESS,
        )
        d.refresh_from_db()
        self.assertEqual(d.response_body, "OK")
        self.assertEqual(d.http_status_code, 200)

    def test_response_body_truncated_on_save(self):
        long_body = "x" * 5000
        d = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_id="evt_trunc",
            event_type="team.member.added",
            payload={},
            response_body=long_body,
        )
        d.refresh_from_db()
        self.assertEqual(len(d.response_body), WebhookDelivery.RESPONSE_BODY_MAX_LENGTH)


class WebhookTenantIsolationTests(TestCase):
    def setUp(self):
        self.team_a = Team.objects.create(name="Team A", slug="team-a")
        self.team_b = Team.objects.create(name="Team B", slug="team-b")

        self.ep_a = WebhookEndpoint.objects.create(
            team=self.team_a,
            url="https://a.example.com/hook",
            events=["*"],
        )
        self.ep_b = WebhookEndpoint.objects.create(
            team=self.team_b,
            url="https://b.example.com/hook",
            events=["*"],
        )

    def test_filter_by_team_returns_only_own_endpoints(self):
        qs = WebhookEndpoint.objects.filter(team=self.team_a)
        self.assertEqual(list(qs), [self.ep_a])

    def test_other_team_endpoint_not_in_queryset(self):
        qs = WebhookEndpoint.objects.filter(team=self.team_a)
        self.assertNotIn(self.ep_b, qs)

    def test_deliveries_scoped_to_endpoint_team(self):
        WebhookDelivery.objects.create(
            endpoint=self.ep_a,
            event_id="evt_1",
            event_type="team.member.added",
            payload={},
        )
        WebhookDelivery.objects.create(
            endpoint=self.ep_b,
            event_id="evt_2",
            event_type="team.member.added",
            payload={},
        )
        team_a_deliveries = WebhookDelivery.objects.filter(
            endpoint__team=self.team_a
        )
        self.assertEqual(team_a_deliveries.count(), 1)
        self.assertEqual(team_a_deliveries.first().event_id, "evt_1")


class WebhookAdminSmokeTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.user = User.objects.create_superuser(
            email="admin@example.com", password="pass123"
        )
        self.client.force_login(self.user)

    def test_endpoint_admin_changelist_loads(self):
        response = self.client.get("/admin/mainapp/webhookendpoint/")
        self.assertEqual(response.status_code, 200)

    def test_delivery_admin_changelist_loads(self):
        response = self.client.get("/admin/mainapp/webhookdelivery/")
        self.assertEqual(response.status_code, 200)

    def test_endpoint_admin_detail_loads(self):
        ep = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )
        response = self.client.get(
            f"/admin/mainapp/webhookendpoint/{ep.pk}/change/"
        )
        self.assertEqual(response.status_code, 200)

    def test_delivery_admin_detail_loads(self):
        ep = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )
        d = WebhookDelivery.objects.create(
            endpoint=ep,
            event_id="evt_test",
            event_type="team.member.added",
            payload={},
        )
        response = self.client.get(
            f"/admin/mainapp/webhookdelivery/{d.pk}/change/"
        )
        self.assertEqual(response.status_code, 200)
