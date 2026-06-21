from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from mainapp.models import Team, TeamInvitation, TeamMembership
from usermodel.models import User


class TeamAPITestBase(TestCase):
    """Shared setup for team API tests."""

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
        self.outsider = User.objects.create_user(
            email="outsider@example.com", password="pass123"
        )

        # Team A
        self.team_a = Team.objects.create(name="Team A", slug="team-a")
        TeamMembership.objects.create(
            team=self.team_a, user=self.owner, role="owner"
        )
        TeamMembership.objects.create(
            team=self.team_a, user=self.admin, role="admin"
        )
        TeamMembership.objects.create(
            team=self.team_a, user=self.member, role="member"
        )

        # Team B (outsider owns it)
        self.team_b = Team.objects.create(name="Team B", slug="team-b")
        TeamMembership.objects.create(
            team=self.team_b, user=self.outsider, role="owner"
        )


class TeamListAPITests(TeamAPITestBase):
    def test_anonymous_rejected(self):
        response = self.client.get("/api/v1/teams/")
        self.assertIn(response.status_code, [401, 403])

    def test_lists_only_user_teams(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/v1/teams/")
        self.assertEqual(response.status_code, 200)
        team_ids = [t["id"] for t in response.data["results"]]
        self.assertIn(str(self.team_a.id), team_ids)
        self.assertNotIn(str(self.team_b.id), team_ids)

    def test_outsider_sees_only_own_teams(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get("/api/v1/teams/")
        team_ids = [t["id"] for t in response.data["results"]]
        self.assertIn(str(self.team_b.id), team_ids)
        self.assertNotIn(str(self.team_a.id), team_ids)

    def test_list_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/v1/teams/")
        team = response.data["results"][0]
        expected = {"id", "name", "slug", "plan", "is_active", "created_at", "updated_at"}
        self.assertEqual(set(team.keys()), expected)

    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_teams_disabled_returns_404(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/v1/teams/")
        self.assertEqual(response.status_code, 404)


class TeamDetailAPITests(TeamAPITestBase):
    def test_member_can_view_team(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(f"/api/v1/teams/{self.team_a.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Team A")
        self.assertIn("member_count", response.data)
        self.assertEqual(response.data["member_count"], 3)

    def test_outsider_cannot_view_team(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(f"/api/v1/teams/{self.team_a.id}/")
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_team_returns_404(self):
        import uuid

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f"/api/v1/teams/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)


class TeamMembersAPITests(TeamAPITestBase):
    def test_member_can_list_members(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(f"/api/v1/teams/{self.team_a.id}/members/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 3)

    def test_outsider_cannot_list_members(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(f"/api/v1/teams/{self.team_a.id}/members/")
        self.assertEqual(response.status_code, 404)

    def test_member_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f"/api/v1/teams/{self.team_a.id}/members/")
        member = response.data["results"][0]
        expected = {"id", "email", "first_name", "last_name", "role", "created_at"}
        self.assertEqual(set(member.keys()), expected)


class TeamInvitationAPITests(TeamAPITestBase):
    def test_owner_can_invite(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "new@example.com", "role": "member"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "new@example.com")
        self.assertEqual(response.data["role"], "member")
        self.assertEqual(response.data["status"], "pending")
        self.assertTrue(
            TeamInvitation.objects.filter(
                team=self.team_a, email="new@example.com"
            ).exists()
        )

    def test_admin_can_invite_member(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "another@example.com", "role": "member"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_admin_cannot_invite_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "nope@example.com", "role": "admin"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_member_cannot_invite(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "blocked@example.com", "role": "member"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_outsider_cannot_invite(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "nope@example.com", "role": "member"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_team_invite_blocked(self):
        """Member of team A cannot invite to team B."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            f"/api/v1/teams/{self.team_b.id}/invitations/",
            {"email": "hack@example.com", "role": "member"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_role_rejected(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "bad@example.com", "role": "owner"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invitation_response_field_contract(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            f"/api/v1/teams/{self.team_a.id}/invitations/",
            {"email": "fields@example.com", "role": "viewer"},
            format="json",
        )
        expected = {"id", "email", "role", "status", "created_at", "expires_at"}
        self.assertEqual(set(response.data.keys()), expected)


@override_settings(API_DOCS_PUBLIC=True)
class TeamAPISchemaTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_schema_includes_team_operations(self):
        response = self.client.get("/api/schema/")
        content = str(response.content)
        self.assertIn("listTeams", content)
        self.assertIn("getTeam", content)
        self.assertIn("listTeamMembers", content)
        self.assertIn("createTeamInvitation", content)
