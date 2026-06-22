"""
Tests for the Idempotency-Key contract on team invitation creation.
"""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from mainapp.models import Team, TeamInvitation, TeamMembership
from speedpycom.models.idempotency import IdempotencyRecord
from usermodel.models import User


class IdempotencyKeyTests(TestCase):
    """Idempotency-Key on POST /api/v1/teams/{team_id}/invitations/."""

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Team", slug="team")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        self.client.force_authenticate(user=self.owner)
        self.url = f"/api/v1/teams/{self.team.id}/invitations/"
        self.payload = {"email": "invite@example.com", "role": "member"}

    def _post(self, key=None, **extra_payload):
        headers = {}
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        data = {**self.payload, **extra_payload}
        return self.client.post(self.url, data, format="json", **headers)

    def test_no_key_creates_normally(self):
        """Requests without Idempotency-Key work as before."""
        response = self._post()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(IdempotencyRecord.objects.exists())

    def test_first_request_with_key_creates_and_stores(self):
        key = str(uuid.uuid4())
        response = self._post(key=key)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(IdempotencyRecord.objects.filter(key=key).exists())

    def test_replay_returns_same_response(self):
        """Same key + same payload returns the stored response without creating a duplicate."""
        key = str(uuid.uuid4())
        r1 = self._post(key=key)
        r2 = self._post(key=key)
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(r2["Idempotency-Replay"], "true")
        self.assertEqual(TeamInvitation.objects.filter(team=self.team).count(), 1)

    def test_different_body_same_key_returns_409(self):
        """Same key with a different request body is rejected."""
        key = str(uuid.uuid4())
        self._post(key=key)
        response = self._post(key=key, email="other@example.com")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(TeamInvitation.objects.filter(team=self.team).count(), 1)

    def test_different_user_cannot_replay(self):
        """Another user's key doesn't collide — they get their own namespace."""
        key = str(uuid.uuid4())
        self._post(key=key)

        other = User.objects.create_user(email="other@example.com", password="pass123")
        TeamMembership.objects.create(team=self.team, user=other, role="admin")
        self.client.force_authenticate(user=other)
        response = self._post(key=key, email="new@example.com")
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("Idempotency-Replay", response)

    def test_invalid_key_returns_400(self):
        response = self._post(key="invalid key with spaces!")
        self.assertEqual(response.status_code, 400)
