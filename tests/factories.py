import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from mainapp.models import Team, TeamInvitation, TeamMembership, UserOTPProfile

User = get_user_model()


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True
    is_email_confirmed = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        if not create:
            return
        self.set_password(extracted or "testpass123")
        self.save()


class TeamFactory(DjangoModelFactory):
    class Meta:
        model = Team

    name = factory.Sequence(lambda n: f"Team {n}")
    slug = factory.Sequence(lambda n: f"team-{n}")
    is_active = True


class TeamMembershipFactory(DjangoModelFactory):
    class Meta:
        model = TeamMembership

    team = factory.SubFactory(TeamFactory)
    user = factory.SubFactory(UserFactory)
    role = "member"


class TeamInvitationFactory(DjangoModelFactory):
    class Meta:
        model = TeamInvitation

    team = factory.SubFactory(TeamFactory)
    invited_by = factory.SubFactory(UserFactory)
    email = factory.Sequence(lambda n: f"invited{n}@example.com")
    role = "member"
    status = "pending"
    # token and expires_at are auto-set by TeamInvitation.save()


class UserOTPProfileFactory(DjangoModelFactory):
    class Meta:
        model = UserOTPProfile

    user = factory.SubFactory(UserFactory)
    otp_enabled = False
    backup_codes_generated = False
