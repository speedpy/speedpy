from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from mainapp.admin.webhooks import WebhookDeliveryAdmin, WebhookEndpointAdmin
from mainapp.models import Team, WebhookDelivery, WebhookEndpoint
from mainapp.webhooks.events import WebhookEvent
from mainapp.webhooks.signing import sign, verify
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


class WebhookSecretRotationModelTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )

    def test_rotate_secret_generates_new_secret(self):
        old_secret = self.endpoint.secret
        self.endpoint.rotate_secret()
        self.assertNotEqual(self.endpoint.secret, old_secret)

    def test_rotate_secret_stores_previous_secret(self):
        old_secret = self.endpoint.secret
        self.endpoint.rotate_secret()
        self.assertEqual(self.endpoint.previous_secret, old_secret)

    def test_rotate_secret_sets_rotated_at(self):
        self.assertIsNone(self.endpoint.secret_rotated_at)
        self.endpoint.rotate_secret()
        self.assertIsNotNone(self.endpoint.secret_rotated_at)

    def test_rotate_secret_sets_expiry(self):
        self.endpoint.rotate_secret()
        self.assertIsNotNone(self.endpoint.previous_secret_expires_at)
        # Default overlap is 24 hours
        expected = self.endpoint.secret_rotated_at + timedelta(seconds=86400)
        self.assertAlmostEqual(
            self.endpoint.previous_secret_expires_at.timestamp(),
            expected.timestamp(),
            delta=2,
        )

    @override_settings(SPEEDPY_WEBHOOK_SECRET_ROTATION_OVERLAP_SECONDS=3600)
    def test_rotate_secret_custom_overlap_from_settings(self):
        self.endpoint.rotate_secret()
        expected = self.endpoint.secret_rotated_at + timedelta(seconds=3600)
        self.assertAlmostEqual(
            self.endpoint.previous_secret_expires_at.timestamp(),
            expected.timestamp(),
            delta=2,
        )

    def test_rotate_secret_explicit_overlap(self):
        self.endpoint.rotate_secret(overlap_seconds=7200)
        expected = self.endpoint.secret_rotated_at + timedelta(seconds=7200)
        self.assertAlmostEqual(
            self.endpoint.previous_secret_expires_at.timestamp(),
            expected.timestamp(),
            delta=2,
        )

    def test_no_previous_secret_before_rotation(self):
        self.assertIsNone(self.endpoint.previous_secret)
        self.assertIsNone(self.endpoint.secret_rotated_at)
        self.assertIsNone(self.endpoint.previous_secret_expires_at)

    def test_rotate_secret_persists_to_db(self):
        self.endpoint.rotate_secret()
        self.endpoint.refresh_from_db()
        self.assertTrue(self.endpoint.previous_secret)
        self.assertIsNotNone(self.endpoint.secret_rotated_at)
        self.assertIsNotNone(self.endpoint.previous_secret_expires_at)

    def test_second_rotation_replaces_previous_secret(self):
        """Re-rotating during overlap discards older previous secret."""
        self.endpoint.rotate_secret()
        first_new_secret = self.endpoint.secret
        first_previous = self.endpoint.previous_secret

        self.endpoint.rotate_secret()
        # previous_secret is now the first_new_secret, not the original
        self.assertEqual(self.endpoint.previous_secret, first_new_secret)
        self.assertNotEqual(self.endpoint.previous_secret, first_previous)

    def test_rotate_does_not_change_endpoint_identity(self):
        """Rotation must not delete endpoint, clear subscriptions, or deactivate."""
        original_id = self.endpoint.id
        original_events = list(self.endpoint.events)
        self.endpoint.rotate_secret()
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.id, original_id)
        self.assertEqual(self.endpoint.events, original_events)
        self.assertTrue(self.endpoint.is_active)


class WebhookSigningRotationTests(TestCase):
    """Verify that both old and new secrets work during the overlap window."""

    def test_verify_with_previous_secret_during_overlap(self):
        old_secret = "old_secret_value"
        new_secret = "new_secret_value"
        timestamp = "1700000000"
        body = b'{"event":"test"}'

        sig_old = sign(old_secret, timestamp, body)
        sig_new = sign(new_secret, timestamp, body)

        # Old secret verifies against old signature
        self.assertTrue(verify(old_secret, timestamp, body, sig_old))
        # New secret verifies against new signature
        self.assertTrue(verify(new_secret, timestamp, body, sig_new))
        # Cross-verify fails (expected)
        self.assertFalse(verify(new_secret, timestamp, body, sig_old))
        self.assertFalse(verify(old_secret, timestamp, body, sig_new))


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


class WebhookSigningTests(TestCase):
    def test_sign_deterministic(self):
        sig = sign("secret123", "1700000000", b'{"event":"test"}')
        self.assertEqual(len(sig), 64)  # SHA-256 hex digest
        # Same inputs produce same output.
        self.assertEqual(sig, sign("secret123", "1700000000", b'{"event":"test"}'))

    def test_sign_differs_with_different_secret(self):
        sig_a = sign("secret_a", "1700000000", b"body")
        sig_b = sign("secret_b", "1700000000", b"body")
        self.assertNotEqual(sig_a, sig_b)

    def test_verify_valid(self):
        sig = sign("mysecret", "12345", b"payload")
        self.assertTrue(verify("mysecret", "12345", b"payload", sig))

    def test_verify_invalid(self):
        self.assertFalse(verify("mysecret", "12345", b"payload", "bad_signature"))

    def test_verify_wrong_timestamp(self):
        sig = sign("mysecret", "12345", b"payload")
        self.assertFalse(verify("mysecret", "99999", b"payload", sig))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class WebhookDeliverTaskTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["*"],
        )

    def _create_delivery(self, **kwargs):
        defaults = {
            "endpoint": self.endpoint,
            "event_id": "evt_test1",
            "event_type": "team.member.added",
            "payload": {"event_id": "evt_test1", "type": "team.member.added", "data": {}},
        }
        defaults.update(kwargs)
        return WebhookDelivery.objects.create(**defaults)

    @patch("mainapp.tasks.webhooks.httpx.Client")
    def test_successful_delivery(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        delivery = self._create_delivery()

        from mainapp.tasks.webhooks import deliver_webhook
        deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.SUCCESS)
        self.assertEqual(delivery.http_status_code, 200)
        self.assertIsNotNone(delivery.delivered_at)
        self.assertEqual(delivery.attempts, 1)

    @patch("mainapp.tasks.webhooks.httpx.Client")
    def test_permanent_failure_4xx(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        delivery = self._create_delivery()

        from mainapp.tasks.webhooks import deliver_webhook
        deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
        self.assertEqual(delivery.http_status_code, 400)
        self.assertIn("400", delivery.error_message)

    @patch("mainapp.tasks.webhooks.httpx.Client")
    def test_retryable_failure_500(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        delivery = self._create_delivery()

        from mainapp.tasks.webhooks import deliver_webhook

        # bind=True tasks get self as first arg; in eager mode, retry raises Retry.
        # We catch that to verify retry was attempted.
        from celery.exceptions import Retry
        with self.assertRaises(Retry):
            deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
        self.assertEqual(delivery.attempts, 1)

    @patch("mainapp.tasks.webhooks.httpx.Client")
    def test_timeout_triggers_retry(self, mock_client_cls):
        import httpx
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(side_effect=httpx.ReadTimeout("timed out")))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        delivery = self._create_delivery()

        from mainapp.tasks.webhooks import deliver_webhook
        from celery.exceptions import Retry
        with self.assertRaises(Retry):
            deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
        self.assertIn("Timeout", delivery.error_message)

    def test_inactive_endpoint_marked_disabled(self):
        self.endpoint.is_active = False
        self.endpoint.save()

        delivery = self._create_delivery()

        from mainapp.tasks.webhooks import deliver_webhook
        deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.DISABLED)

    @patch("mainapp.tasks.webhooks.httpx.Client")
    def test_redirect_not_followed(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.text = ""
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        delivery = self._create_delivery()

        from mainapp.tasks.webhooks import deliver_webhook
        deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
        self.assertEqual(delivery.http_status_code, 301)

    def test_nonexistent_delivery_does_not_crash(self):
        from mainapp.tasks.webhooks import deliver_webhook
        deliver_webhook(999999)  # should log warning and return


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class WebhookDispatchTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=["team.member.added"],
        )

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_dispatch_creates_deliveries_for_matching_endpoints(self, mock_delay):
        from mainapp.webhooks.dispatch import dispatch_event

        with self.captureOnCommitCallbacks(execute=True):
            ids = dispatch_event(self.team, "team.member.added", {"user_id": "123"})

        self.assertEqual(len(ids), 1)
        delivery = WebhookDelivery.objects.get(pk=ids[0])
        self.assertEqual(delivery.event_type, "team.member.added")
        self.assertEqual(delivery.payload["data"]["user_id"], "123")
        mock_delay.assert_called_once_with(delivery.pk)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_dispatch_skips_non_matching_events(self, mock_delay):
        from mainapp.webhooks.dispatch import dispatch_event

        with self.captureOnCommitCallbacks(execute=True):
            ids = dispatch_event(self.team, "user.profile.updated", {"user_id": "123"})

        self.assertEqual(len(ids), 0)
        mock_delay.assert_not_called()

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_dispatch_skips_inactive_endpoints(self, mock_delay):
        self.endpoint.is_active = False
        self.endpoint.save()

        from mainapp.webhooks.dispatch import dispatch_event

        with self.captureOnCommitCallbacks(execute=True):
            ids = dispatch_event(self.team, "team.member.added", {"user_id": "123"})

        self.assertEqual(len(ids), 0)
        mock_delay.assert_not_called()


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
