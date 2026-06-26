"""
Tests for production-path webhook event dispatch (ticket #47).

These tests verify that ``dispatch_event()`` is called from actual business
actions (signal receivers and views), not just in isolation.
"""

import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from mainapp.models import Team, TeamInvitation, TeamMembership, WebhookDelivery, WebhookEndpoint
from mainapp.webhooks.events import WebhookEvent
from usermodel.models import User


class TeamMemberAddedSignalTests(TestCase):
    """Verify ``team.member.added`` fires when a TeamMembership is created."""

    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=[WebhookEvent.TEAM_MEMBER_ADDED],
        )
        self.user = User.objects.create_user(email="new@example.com", password="pass")
        self.inviter = User.objects.create_user(email="boss@example.com", password="pass")

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_membership_creation_dispatches_event(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            membership = TeamMembership.objects.create(
                team=self.team,
                user=self.user,
                role="member",
                invited_by=self.inviter,
                invite_accepted_at=timezone.now(),
            )

        delivery = WebhookDelivery.objects.get(endpoint=self.endpoint)
        self.assertEqual(delivery.event_type, WebhookEvent.TEAM_MEMBER_ADDED)
        self.assertEqual(delivery.payload["data"]["user_id"], str(self.user.id))
        self.assertEqual(delivery.payload["data"]["role"], "member")
        self.assertEqual(delivery.payload["data"]["team_id"], str(self.team.id))
        self.assertEqual(delivery.payload["data"]["membership_id"], str(membership.id))
        self.assertEqual(delivery.payload["data"]["invited_by_id"], str(self.inviter.id))
        self.assertIsNotNone(delivery.payload["data"]["invite_accepted_at"])
        mock_delay.assert_called_once_with(delivery.pk)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_invitation_accept_dispatches_member_added(self, mock_delay):
        """TeamInvitation.accept() creates a membership and triggers the signal."""
        invitation = TeamInvitation.objects.create(
            team=self.team,
            invited_by=self.inviter,
            email="new@example.com",
            role="member",
        )
        # The invitation creation itself fires team.invitation.created; clear those.
        WebhookDelivery.objects.all().delete()

        with self.captureOnCommitCallbacks(execute=True):
            invitation.accept(self.user)

        deliveries = WebhookDelivery.objects.filter(
            event_type=WebhookEvent.TEAM_MEMBER_ADDED
        )
        self.assertEqual(deliveries.count(), 1)
        self.assertEqual(deliveries[0].payload["data"]["user_id"], str(self.user.id))

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_no_dispatch_on_membership_update(self, mock_delay):
        """Updating an existing membership should not dispatch."""
        with self.captureOnCommitCallbacks(execute=True):
            membership = TeamMembership.objects.create(
                team=self.team, user=self.user, role="member"
            )

        mock_delay.reset_mock()
        WebhookDelivery.objects.all().delete()

        with self.captureOnCommitCallbacks(execute=True):
            membership.role = "admin"
            membership.save()

        self.assertEqual(WebhookDelivery.objects.count(), 0)
        mock_delay.assert_not_called()

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_no_delivery_without_matching_endpoint(self, mock_delay):
        """If the endpoint doesn't subscribe, no delivery is created."""
        self.endpoint.events = [WebhookEvent.USER_PROFILE_UPDATED]
        self.endpoint.save()

        with self.captureOnCommitCallbacks(execute=True):
            TeamMembership.objects.create(
                team=self.team, user=self.user, role="member"
            )

        self.assertEqual(WebhookDelivery.objects.count(), 0)


class TeamInvitationCreatedSignalTests(TestCase):
    """Verify ``team.invitation.created`` fires when a TeamInvitation is created."""

    def setUp(self):
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=[WebhookEvent.TEAM_INVITATION_CREATED],
        )
        self.inviter = User.objects.create_user(email="boss@example.com", password="pass")
        TeamMembership.objects.create(
            team=self.team, user=self.inviter, role="owner"
        )
        # Clear the membership-created delivery
        WebhookDelivery.objects.all().delete()

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_invitation_creation_dispatches_event(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            invitation = TeamInvitation.objects.create(
                team=self.team,
                invited_by=self.inviter,
                email="bob@example.com",
                role="member",
            )

        delivery = WebhookDelivery.objects.get(
            event_type=WebhookEvent.TEAM_INVITATION_CREATED
        )
        data = delivery.payload["data"]
        self.assertEqual(data["team_id"], str(self.team.id))
        self.assertEqual(data["invitation_id"], str(invitation.id))
        self.assertEqual(data["email"], "bob@example.com")
        self.assertEqual(data["role"], "member")
        self.assertEqual(data["invited_by_id"], str(self.inviter.id))
        # expires_at may be None when created without explicit value
        # (UUID PKs cause save()'s auto-expiry branch to be skipped)
        mock_delay.assert_called_once()

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_api_invitation_dispatches_event(self, mock_delay):
        """POST /api/v1/teams/{id}/invitations/ triggers the signal."""
        client = APIClient()
        client.force_authenticate(user=self.inviter)
        url = f"/api/v1/teams/{self.team.id}/invitations/"

        with self.captureOnCommitCallbacks(execute=True):
            response = client.post(
                url,
                {"email": "api@example.com", "role": "member"},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        delivery = WebhookDelivery.objects.get(
            event_type=WebhookEvent.TEAM_INVITATION_CREATED
        )
        self.assertEqual(delivery.payload["data"]["email"], "api@example.com")

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_idempotent_replay_does_not_create_duplicate_delivery(self, mock_delay):
        """Replayed idempotent requests must not produce a second webhook delivery."""
        client = APIClient()
        client.force_authenticate(user=self.inviter)
        url = f"/api/v1/teams/{self.team.id}/invitations/"
        key = str(uuid.uuid4())

        with self.captureOnCommitCallbacks(execute=True):
            r1 = client.post(
                url,
                {"email": "replay@example.com", "role": "member"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        self.assertEqual(r1.status_code, 201)
        deliveries_after_first = WebhookDelivery.objects.filter(
            event_type=WebhookEvent.TEAM_INVITATION_CREATED
        ).count()

        with self.captureOnCommitCallbacks(execute=True):
            r2 = client.post(
                url,
                {"email": "replay@example.com", "role": "member"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r2["Idempotency-Replay"], "true")
        # No new delivery created by the replay
        self.assertEqual(
            WebhookDelivery.objects.filter(
                event_type=WebhookEvent.TEAM_INVITATION_CREATED
            ).count(),
            deliveries_after_first,
        )


class UserProfileUpdatedAPITests(TestCase):
    """Verify ``user.profile.updated`` dispatches from the API PATCH endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="profile@example.com",
            password="pass",
            first_name="Ada",
            last_name="Lovelace",
        )
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=[WebhookEvent.USER_PROFILE_UPDATED],
        )
        TeamMembership.objects.create(
            team=self.team, user=self.user, role="member"
        )
        # Clear membership-created deliveries
        WebhookDelivery.objects.all().delete()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_patch_with_changed_field_dispatches(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                "/api/v1/me/",
                {"first_name": "Grace"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        delivery = WebhookDelivery.objects.get(
            event_type=WebhookEvent.USER_PROFILE_UPDATED
        )
        data = delivery.payload["data"]
        self.assertEqual(data["user_id"], str(self.user.id))
        self.assertIn("first_name", data["changed_fields"])
        self.assertIsNotNone(data["updated_at"])

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_empty_patch_does_not_dispatch(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                "/api/v1/me/",
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_noop_patch_does_not_dispatch(self, mock_delay):
        """Submitting the same value should not dispatch."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                "/api/v1/me/",
                {"first_name": "Ada"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_dispatch_to_multiple_teams(self, mock_delay):
        """user.profile.updated fires once per active team."""
        team_b = Team.objects.create(name="Team B", slug="team-b")
        WebhookEndpoint.objects.create(
            team=team_b,
            url="https://b.example.com/hook",
            events=[WebhookEvent.USER_PROFILE_UPDATED],
        )
        TeamMembership.objects.create(team=team_b, user=self.user, role="member")
        WebhookDelivery.objects.all().delete()

        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(
                "/api/v1/me/",
                {"first_name": "Grace"},
                format="json",
            )

        deliveries = WebhookDelivery.objects.filter(
            event_type=WebhookEvent.USER_PROFILE_UPDATED
        )
        self.assertEqual(deliveries.count(), 2)
        teams = {d.endpoint.team_id for d in deliveries}
        self.assertEqual(teams, {self.team.id, team_b.id})

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_expired_membership_excluded(self, mock_delay):
        """Expired memberships should not receive the event."""
        team_expired = Team.objects.create(name="Expired Team", slug="expired")
        WebhookEndpoint.objects.create(
            team=team_expired,
            url="https://expired.example.com/hook",
            events=[WebhookEvent.USER_PROFILE_UPDATED],
        )
        from datetime import timedelta

        TeamMembership.objects.create(
            team=team_expired,
            user=self.user,
            role="member",
            access_expires_at=timezone.now() - timedelta(days=1),
        )
        WebhookDelivery.objects.all().delete()

        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(
                "/api/v1/me/",
                {"first_name": "Grace"},
                format="json",
            )

        # Only the active team should get a delivery, not the expired one
        deliveries = WebhookDelivery.objects.filter(
            event_type=WebhookEvent.USER_PROFILE_UPDATED
        )
        self.assertEqual(deliveries.count(), 1)
        self.assertEqual(deliveries[0].endpoint.team_id, self.team.id)

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_inactive_team_excluded(self, mock_delay):
        """Inactive teams should not receive the event."""
        inactive_team = Team.objects.create(
            name="Inactive", slug="inactive", is_active=False
        )
        WebhookEndpoint.objects.create(
            team=inactive_team,
            url="https://inactive.example.com/hook",
            events=[WebhookEvent.USER_PROFILE_UPDATED],
        )
        TeamMembership.objects.create(
            team=inactive_team, user=self.user, role="member"
        )
        WebhookDelivery.objects.all().delete()

        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(
                "/api/v1/me/",
                {"first_name": "Grace"},
                format="json",
            )

        deliveries = WebhookDelivery.objects.filter(
            event_type=WebhookEvent.USER_PROFILE_UPDATED
        )
        self.assertEqual(deliveries.count(), 1)
        self.assertEqual(deliveries[0].endpoint.team_id, self.team.id)


class UserProfileUpdatedFormTests(TestCase):
    """Verify ``user.profile.updated`` dispatches from the HTML profile edit view."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="form@example.com",
            password="pass",
            first_name="Ada",
            last_name="Lovelace",
        )
        self.team = Team.objects.create(name="Acme", slug="acme")
        self.endpoint = WebhookEndpoint.objects.create(
            team=self.team,
            url="https://example.com/hook",
            events=[WebhookEvent.USER_PROFILE_UPDATED],
        )
        TeamMembership.objects.create(
            team=self.team, user=self.user, role="member"
        )
        WebhookDelivery.objects.all().delete()
        self.client.login(email="form@example.com", password="pass")

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_form_submit_with_change_dispatches(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/accounts/profile/",
                {"first_name": "Grace", "last_name": "Lovelace"},
            )

        self.assertEqual(response.status_code, 302)
        delivery = WebhookDelivery.objects.get(
            event_type=WebhookEvent.USER_PROFILE_UPDATED
        )
        self.assertIn("first_name", delivery.payload["data"]["changed_fields"])

    @patch("mainapp.tasks.webhooks.deliver_webhook.delay")
    def test_form_submit_no_change_does_not_dispatch(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/accounts/profile/",
                {"first_name": "Ada", "last_name": "Lovelace"},
            )

        self.assertEqual(WebhookDelivery.objects.count(), 0)
