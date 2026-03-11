import os

import pytest

# Ensure postgres is used (matches docker-compose db service credentials).
# Override via DATABASE_URL env var if running outside Docker.
os.environ.setdefault("DATABASE_URL", "postgres://speedpycom:speedpycom@db/speedpycom")

from django.conf import settings  # noqa: E402 (must come after env setup)

from tests.factories import (  # noqa: E402
    TeamFactory,
    TeamInvitationFactory,
    TeamMembershipFactory,
    UserFactory,
)


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


# ── Team fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def team(db):
    return TeamFactory()


@pytest.fixture
def owner_membership(db, user, team):
    """Current user is the owner of the team."""
    return TeamMembershipFactory(user=user, team=team, role="owner")


@pytest.fixture
def member_user(db):
    return UserFactory()


@pytest.fixture
def member_membership(db, member_user, team):
    """A second team member (role=member) for permission-related tests."""
    return TeamMembershipFactory(user=member_user, team=team, role="member")


@pytest.fixture
def invitation(db, team, user):
    """A pending team invitation created by the owner."""
    return TeamInvitationFactory(team=team, invited_by=user)
