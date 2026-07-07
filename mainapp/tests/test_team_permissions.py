"""
Tests that team permission checks run BEFORE view handlers.

TeamAdminRequiredMixin used to check the role only after
super().dispatch() had already run the handler (and its side effects).
These tests assert both the response code and that no mutation happened.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from mainapp.models import Team, TeamInvitation, TeamMembership
from usermodel.models import User


class TeamPermissionTestBase(TestCase):
    """Shared setup: a team with two owners, an admin, a member and a viewer."""

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pass123"
        )
        self.owner2 = User.objects.create_user(
            email="owner2@example.com", password="pass123"
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

        self.team = Team.objects.create(name="Team A", slug="team-a")
        self.owner_membership = TeamMembership.objects.create(
            team=self.team, user=self.owner, role="owner"
        )
        self.owner2_membership = TeamMembership.objects.create(
            team=self.team, user=self.owner2, role="owner"
        )
        self.admin_membership = TeamMembership.objects.create(
            team=self.team, user=self.admin, role="admin"
        )
        self.member_membership = TeamMembership.objects.create(
            team=self.team, user=self.member, role="member"
        )
        self.viewer_membership = TeamMembership.objects.create(
            team=self.team, user=self.viewer, role="viewer"
        )


class TeamSettingsPermissionTests(TeamPermissionTestBase):
    """A member/viewer POST must not save settings before the 403."""

    def _post_settings(self, user):
        self.client.force_login(user)
        return self.client.post(
            reverse("team_settings", kwargs={"team_id": self.team.pk}),
            {"name": "Hacked Name", "slug": "hacked-slug"},
        )

    def test_member_post_returns_403_and_saves_nothing(self):
        response = self._post_settings(self.member)
        self.assertEqual(response.status_code, 403)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Team A")
        self.assertEqual(self.team.slug, "team-a")

    def test_viewer_post_returns_403_and_saves_nothing(self):
        response = self._post_settings(self.viewer)
        self.assertEqual(response.status_code, 403)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Team A")
        self.assertEqual(self.team.slug, "team-a")

    def test_member_get_returns_403(self):
        self.client.force_login(self.member)
        response = self.client.get(
            reverse("team_settings", kwargs={"team_id": self.team.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_post_saves(self):
        response = self._post_settings(self.admin)
        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Hacked Name")

    def test_owner_post_saves(self):
        response = self._post_settings(self.owner)
        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Hacked Name")


class RevokeInvitationPermissionTests(TeamPermissionTestBase):
    """A member/viewer POST must not revoke the invitation before the 403."""

    def setUp(self):
        super().setUp()
        self.invitation = TeamInvitation.objects.create(
            team=self.team,
            invited_by=self.owner,
            email="newcomer@example.com",
            role="member",
        )

    def _post_revoke(self, user):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "revoke_invitation",
                kwargs={"team_id": self.team.pk, "invitation_id": self.invitation.pk},
            )
        )

    def test_member_post_returns_403_and_invitation_stays_pending(self):
        response = self._post_revoke(self.member)
        self.assertEqual(response.status_code, 403)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, "pending")

    def test_viewer_post_returns_403_and_invitation_stays_pending(self):
        response = self._post_revoke(self.viewer)
        self.assertEqual(response.status_code, 403)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, "pending")

    def test_admin_post_revokes(self):
        response = self._post_revoke(self.admin)
        self.assertEqual(response.status_code, 302)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, "revoked")


class UpdateMemberRolePermissionTests(TeamPermissionTestBase):
    """Permission checks must see the target's role BEFORE any mutation."""

    def _post_role(self, user, target_membership, role):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "update_member_role",
                kwargs={
                    "team_id": self.team.pk,
                    "membership_id": target_membership.pk,
                },
            ),
            {"role": role},
        )

    def test_admin_cannot_demote_owner(self):
        """The old code saved the demotion, then checked can_manage_member
        against the already-mutated role — which passed, committing silently."""
        with self.captureOnCommitCallbacks() as callbacks:
            response = self._post_role(self.admin, self.owner_membership, "member")
        self.assertEqual(response.status_code, 403)
        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, "owner")
        self.assertEqual(callbacks, [])

    def test_admin_cannot_demote_other_admin(self):
        other_admin = User.objects.create_user(
            email="admin2@example.com", password="pass123"
        )
        other_admin_membership = TeamMembership.objects.create(
            team=self.team, user=other_admin, role="admin"
        )
        response = self._post_role(self.admin, other_admin_membership, "member")
        self.assertEqual(response.status_code, 403)
        other_admin_membership.refresh_from_db()
        self.assertEqual(other_admin_membership.role, "admin")

    def test_admin_get_for_owner_target_returns_403(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse(
                "update_member_role",
                kwargs={
                    "team_id": self.team.pk,
                    "membership_id": self.owner_membership.pk,
                },
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_cannot_change_own_role(self):
        """With two owners the last-owner guard does not apply; the
        self-change guard must still block the save."""
        with self.captureOnCommitCallbacks() as callbacks:
            response = self._post_role(self.owner, self.owner_membership, "member")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("team_members", kwargs={"team_id": self.team.pk}),
        )
        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, "owner")
        self.assertEqual(callbacks, [])

    def test_member_post_returns_403_and_changes_nothing(self):
        response = self._post_role(self.member, self.viewer_membership, "member")
        self.assertEqual(response.status_code, 403)
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.role, "viewer")

    @patch("mainapp.views.team_members.current_app.send_task")
    def test_admin_can_change_member_role(self, mock_send_task):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_role(self.admin, self.member_membership, "viewer")
        self.assertEqual(response.status_code, 302)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, "viewer")
        mock_send_task.assert_called_once()

    @patch("mainapp.views.team_members.current_app.send_task")
    def test_owner_can_promote_member_to_admin(self, mock_send_task):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_role(self.owner, self.member_membership, "admin")
        self.assertEqual(response.status_code, 302)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, "admin")
        mock_send_task.assert_called_once()


class InviteMemberPermissionTests(TeamPermissionTestBase):
    """Regression guard: non-admins get 403 and no invitation is created."""

    def _post_invite(self, user):
        self.client.force_login(user)
        return self.client.post(
            reverse("invite_member", kwargs={"team_id": self.team.pk}),
            {"email": "newcomer@example.com", "role": "member", "message": ""},
        )

    def test_member_post_returns_403_and_creates_nothing(self):
        with self.captureOnCommitCallbacks() as callbacks:
            response = self._post_invite(self.member)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TeamInvitation.objects.count(), 0)
        self.assertEqual(callbacks, [])

    def test_viewer_post_returns_403_and_creates_nothing(self):
        response = self._post_invite(self.viewer)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TeamInvitation.objects.count(), 0)

    @patch("mainapp.views.team_members.current_app.send_task")
    def test_admin_post_creates_invitation(self, mock_send_task):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_invite(self.admin)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TeamInvitation.objects.count(), 1)
        mock_send_task.assert_called_once()


class RemoveMemberPermissionTests(TeamPermissionTestBase):
    """Regression guard: non-admins get 403 and the membership survives."""

    def _post_remove(self, user, target_membership):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "remove_member",
                kwargs={
                    "team_id": self.team.pk,
                    "membership_id": target_membership.pk,
                },
            )
        )

    def test_member_post_returns_403_and_membership_survives(self):
        response = self._post_remove(self.member, self.viewer_membership)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            TeamMembership.objects.filter(pk=self.viewer_membership.pk).exists()
        )

    def test_viewer_post_returns_403_and_membership_survives(self):
        response = self._post_remove(self.viewer, self.member_membership)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            TeamMembership.objects.filter(pk=self.member_membership.pk).exists()
        )

    def test_admin_can_remove_member(self):
        response = self._post_remove(self.admin, self.member_membership)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            TeamMembership.objects.filter(pk=self.member_membership.pk).exists()
        )
