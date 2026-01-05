import uuid
import secrets
from django.db import models
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from speedpycom.models import BaseModel
from mainapp.subscription_plans import SUBSCRIPTION_PLANS, SUBSCRIPTION_PLANS_CHOICES


class Team(BaseModel):
    """
    Team model is the foreign key for all multi-tenant models.

    Stores information about team, plan, and team configuration.

    Subscription information should be stored externally,
    because different payment methods can be used, or none used at all.
    """

    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=100, unique=True)
    logo = models.ImageField(upload_to="team_logos/", blank=True, null=True)
    # plans should be stored in mainapp.subscription_plans
    plan = models.CharField(
        max_length=50,
        db_index=True,
        default="free",
        choices=SUBSCRIPTION_PLANS_CHOICES,
    )

    is_active = models.BooleanField(default=True)

    # team limits
    # extend this to match your application needs
    # must be updated on plan change
    limits_max_team_members = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        verbose_name = "Team"
        verbose_name_plural = "Teams"

    def __str__(self):
        return self.name

    def get_members(self):
        return (
            self.teammembership_set.filter()
            .select_related("user", "invited_by")
            .order_by("role", "created_at")
        )

    def get_invitations(self):
        return (
            self.teaminvitation_set.filter(
                Q(expires_at__gt=timezone.now()) | Q(expires_at__isnull=True),
                status="pending",
            )
            .select_related("invited_by")
            .order_by("-created_at")
        )

    # Plan & Quota Methods
    def get_plan_config(self):
        """Get current plan configuration from settings"""
        return SUBSCRIPTION_PLANS.get(self.plan, {})

    # create can_* for every check of quota/usage


class TeamModel(BaseModel):
    """
    This is a mixin for multi-tenancy enabled models.
    All models that should be scoped to a team should inherit from this.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    class Meta:
        abstract = True


class TeamMembership(TeamModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_membership",
    )

    role = models.CharField(
        max_length=50,
        choices=(
            (
                "owner",
                "Owner",
            ),  # Full control, billing, delete team, transfer ownership
            ("admin", "Admin"),  # Manage team, invite members
            ("member", "Member"),  # Create/edit, view data
            ("viewer", "Viewer"),  # Read-only access
        ),
        default="member",
        db_index=True,
    )
    # Invitation & Onboarding

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_invitations_sent",
    )
    invite_accepted_at = models.DateTimeField(null=True, blank=True)
    access_expires_at = models.DateTimeField(
        null=True, blank=True, help_text=_("For temporary/contractor access")
    )

    class Meta:
        verbose_name = _("Team Membership")
        verbose_name_plural = _("Team Memberships")
        unique_together = [["team", "user"]]
        ordering = ["role", "created_at"]

    def can_manage_member(self, target_membership):
        """
        Check if this user can manage another team member.

        Rules:
        - Owner can manage anyone
        - Admin can manage members and viewers (NOT owners or other admins)
        - Members and viewers cannot manage anyone
        """
        if self.role == "owner":
            return True

        if self.role == "admin":
            return target_membership.role in ["member", "viewer"]

        return False

    def can_invite_role(self, role):
        """Check if this user can invite someone with given role"""
        if self.role == "owner":
            return True

        if self.role == "admin":
            return role in ["member", "viewer"]

        return False


class TeamInvitation(TeamModel):
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_invitations",
    )

    # Invitee Information
    email = models.EmailField(
        db_index=True,
        help_text=_("Email address to send invitation to"),
        blank=True,
        null=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_invitations",
        help_text=_("Set if user exists in system"),
    )

    # Role Assignment
    role = models.CharField(
        max_length=20,
        choices=[
            ("admin", "Admin"),
            ("member", "Member"),
            ("viewer", "Viewer"),
        ],
        default="member",
        help_text=_("Role to assign when invitation is accepted"),
    )

    # Invitation Token & Security
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text=_("Secure token for invitation URL"),
    )

    # Status & Lifecycle
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("accepted", "Accepted"),
            ("declined", "Declined"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ],
        default="pending",
        db_index=True,
    )
    # Personal Message
    message = models.TextField(
        blank=True, help_text=_("Optional personal message from inviter")
    )

    # Expiration
    expires_at = models.DateTimeField(
        help_text=_("Invitation expiration date"), db_index=True, null=True, blank=True
    )

    class Meta:
        verbose_name = _("Team Invitation")
        verbose_name_plural = _("Team Invitations")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invitation to {self.email} for {self.team.name}"

    def save(self, *args, **kwargs):
        """Generate token and set expiration on creation"""
        if not self.token:
            self.token = secrets.token_urlsafe(48)

        # Set expiration to 7 days from now if not set
        if not self.expires_at and not self.pk:
            from datetime import timedelta

            self.expires_at = timezone.now() + timedelta(days=7)

        super().save(*args, **kwargs)

    def is_valid(self):
        """Check if invitation is still valid"""
        if self.status != "pending":
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def accept(self, user):
        """Accept invitation and create membership"""
        from django.core.exceptions import ValidationError

        if not self.is_valid():
            raise ValidationError("This invitation is no longer valid")

        if TeamMembership.objects.filter(team=self.team, user=user).exists():
            raise ValidationError("You are already a member of this team")

        membership = TeamMembership.objects.create(
            team=self.team,
            user=user,
            role=self.role,
            invited_by=self.invited_by,
            invite_accepted_at=timezone.now(),
        )

        self.status = "accepted"
        self.user = user
        self.save()

        return membership

    def decline(self):
        """Decline invitation"""
        self.status = "declined"
        self.save()

    def revoke(self):
        """Revoke invitation (by admin/owner)"""
        self.status = "revoked"
        self.save()
