"""
Tests for team-related views.

These tests are skipped when SPEEDPY_TEAMS_ENABLED=False (separate run).

POST-only views not tested here:
- DeclineInvitationView
- RemoveMemberView
- RevokeInvitationView
"""
import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.teams

skip_if_teams_disabled = pytest.mark.skipif(
    not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True),
    reason="SPEEDPY_TEAMS_ENABLED is False",
)


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_create_requires_login(client):
    response = client.get(reverse("team_create"))
    assert response.status_code == 302


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_create(auth_client):
    response = auth_client.get(reverse("team_create"))
    assert response.status_code == 200


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_dashboard_requires_login(client, team, owner_membership):
    response = client.get(reverse("team_dashboard", kwargs={"team_id": team.pk}))
    assert response.status_code == 302


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_dashboard(auth_client, team, owner_membership):
    response = auth_client.get(reverse("team_dashboard", kwargs={"team_id": team.pk}))
    assert response.status_code == 200


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_settings_requires_login(client, team, owner_membership):
    response = client.get(reverse("team_settings", kwargs={"team_id": team.pk}))
    assert response.status_code == 302


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_settings(auth_client, team, owner_membership):
    response = auth_client.get(reverse("team_settings", kwargs={"team_id": team.pk}))
    assert response.status_code == 200


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_members_requires_login(client, team, owner_membership):
    response = client.get(reverse("team_members", kwargs={"team_id": team.pk}))
    assert response.status_code == 302


@skip_if_teams_disabled
@pytest.mark.django_db
def test_team_members(auth_client, team, owner_membership):
    response = auth_client.get(reverse("team_members", kwargs={"team_id": team.pk}))
    assert response.status_code == 200


@skip_if_teams_disabled
@pytest.mark.django_db
def test_invite_member_requires_login(client, team, owner_membership):
    response = client.get(reverse("invite_member", kwargs={"team_id": team.pk}))
    assert response.status_code == 302


@skip_if_teams_disabled
@pytest.mark.django_db
def test_invite_member(auth_client, team, owner_membership):
    response = auth_client.get(reverse("invite_member", kwargs={"team_id": team.pk}))
    assert response.status_code == 200


@skip_if_teams_disabled
@pytest.mark.django_db
def test_accept_invitation_requires_login(client, invitation):
    response = client.get(
        reverse("accept_invitation", kwargs={"token": invitation.token})
    )
    assert response.status_code == 302


@skip_if_teams_disabled
@pytest.mark.django_db
def test_accept_invitation(auth_client, invitation):
    """AcceptInvitationView renders even for invalid/already-used tokens."""
    response = auth_client.get(
        reverse("accept_invitation", kwargs={"token": invitation.token})
    )
    assert response.status_code == 200


@skip_if_teams_disabled
@pytest.mark.django_db
def test_update_member_role(auth_client, team, owner_membership, member_membership):
    """Owner can GET the update-role form for a member."""
    response = auth_client.get(
        reverse(
            "update_member_role",
            kwargs={
                "team_id": team.pk,
                "membership_id": member_membership.pk,
            },
        )
    )
    assert response.status_code == 200
