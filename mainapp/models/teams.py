import uuid
import secrets
import structlog
from django.db import models
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from speedpycom.models import BaseModel
from mainapp.subscription_plans import (
    SUBSCRIPTION_PLANS_CHOICES,
    get_plan_config as get_plan_config_for_key,
)

logger = structlog.get_logger(__name__)


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

    # Owner-requested deletion, with an undo window (see request_deletion()).
    # deletion_scheduled_at is the moment the purge task may delete the row; it
    # is the single flag for "deletion is pending", so clearing it is the undo.
    deletion_scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the scheduled deletion may run. Null means no deletion is pending.",
    )
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    deletion_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The owner who asked for the deletion. Kept for the audit trail only.",
    )

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
        """Get current plan configuration from the canonical plan registry.

        Delegates to ``mainapp.subscription_plans.get_plan_config`` so the
        registry stays the single source of truth (falls back to the free plan
        for unknown/stale keys).
        """
        return get_plan_config_for_key(self.plan)

    # create can_* for every check of quota/usage

    # ------------------------------------------------------------------
    # Deletion with an undo window
    # ------------------------------------------------------------------
    # A team is the foreign key of every tenant row, so deleting one is the
    # most destructive action a customer can take in the product — and until
    # now there was no way to do it at all, which left abandoned teams (and
    # their still-live public data) in the database forever.
    #
    # The delay is a setting, not a constant: SPEEDPY_TEAM_DELETION_DELAY_HOURS.
    # 0 means delete on the click. Anything else schedules the deletion and
    # leaves the team fully working, so the owner can undo it. The team is
    # deliberately NOT deactivated while scheduled: TeamViewMixin resolves
    # is_active teams only, so deactivating would hide the undo button behind a
    # 404 from the one person allowed to press it.

    @property
    def is_deletion_scheduled(self):
        return self.deletion_scheduled_at is not None

    @staticmethod
    def deletion_delay_hours():
        """The configured undo window, in hours. Never negative."""
        return max(0, int(getattr(settings, "SPEEDPY_TEAM_DELETION_DELAY_HOURS", 24)))

    def deletion_blocked_reason(self):
        """Why this team may not be deleted right now, or None if it may.

        The one rule that is not about permissions: a team with a live
        subscription must not be deleted, or the payment method on file keeps
        being charged for something that no longer exists. Cancelling is
        enough — we do not wait for the paid period to end, because a canceled
        subscription bills nobody again.

        Deliberately NOT gated on ``SPEEDPY_BILLING_ENABLED``. The flag says
        whether the billing UI is offered; it says nothing about whether a
        subscription row exists. A project that switches the flag off must not
        thereby gain the power to delete a team the provider is still charging.

        ``ACTIVE_ISH_STATUSES`` is the right set: ``past_due`` can still retry
        a card and ``paused`` can resume. Every row is checked, not the newest
        one — the model deliberately allows more than one live row so that
        abnormal states stay visible.
        """
        from mainapp.models.billing import BillingSubscription

        if BillingSubscription.objects.filter(
            billable_type="team",
            billable_id=str(self.pk),
            status__in=BillingSubscription.ACTIVE_ISH_STATUSES,
        ).exists():
            return (
                "This team still has a live subscription. Cancel it first — "
                "otherwise the payment method on file would keep being charged "
                "for a team that no longer exists."
            )
        return None

    def delete(self, *args, **kwargs):
        """Refuse to delete a team the provider may still charge.

        The rule has to hold at the last possible moment, not only in the view
        that asked: admin, a shell, a management command and the purge task all
        arrive here. A bulk ``Team.objects.filter(...).delete()`` still walks
        around it — Django's collector never calls this method — which is why
        the purge task deletes teams one at a time.
        """
        reason = self.deletion_blocked_reason()
        if reason:
            logger.warning(
                "team_deletion_blocked_billing",
                team_id=str(self.pk),
                team_slug=self.slug,
            )
            raise TeamDeletionBlocked(reason)
        return super().delete(*args, **kwargs)

    def request_deletion(self, by_user=None, now=None):
        """Delete the team, or schedule it, depending on the configured delay.

        Returns "deleted" or "scheduled" so the caller can report what
        happened. Raises TeamDeletionBlocked when a live subscription stands in
        the way; callers must show that message rather than swallow it.
        """
        if self.is_deletion_scheduled:
            # Not an error worth an exception, but it must not silently move the
            # deadline further out: the owner would think they had cancelled.
            return "already_scheduled"

        reason = self.deletion_blocked_reason()
        if reason:
            raise TeamDeletionBlocked(reason)

        hours = self.deletion_delay_hours()
        now = now or timezone.now()

        # Mark FIRST, delete second — even with no delay. The mark is what shuts
        # the billing doors (checkout and the provider portal both refuse a
        # scheduled team), and it is what lets the hourly task finish the job if
        # this attempt cannot. Without it, a zero-hour deletion that failed part
        # way left no record that anybody had asked for it.
        #
        # Compare-and-set, so two simultaneous first requests cannot each write
        # their own deadline with the later one winning.
        scheduled_at = now + timezone.timedelta(hours=hours)
        claimed = Team.objects.filter(
            pk=self.pk, deletion_scheduled_at__isnull=True
        ).update(
            deletion_scheduled_at=scheduled_at,
            deletion_requested_at=now,
            deletion_requested_by=by_user,
            updated_at=now,
        )
        self.refresh_from_db(
            fields=[
                "deletion_scheduled_at",
                "deletion_requested_at",
                "deletion_requested_by",
            ]
        )
        if not claimed:
            return "already_scheduled"

        logger.warning(
            "team_deletion_scheduled",
            team_id=str(self.pk),
            team_slug=self.slug,
            requested_by_id=str(by_user.pk) if by_user else None,
            deletion_scheduled_at=self.deletion_scheduled_at.isoformat(),
            delay_hours=hours,
        )

        if hours:
            return "scheduled"

        # No delay: finish it now. Through the finalizer, never self.delete() —
        # the cleanup hooks are what remove the objects the cascade cannot see.
        try:
            finalize_team_deletion(self)
            return "deleted"
        except (TeamCleanupFailed, TeamDeletionBlocked):
            # Both are already logged with their reason. The team stays marked,
            # so its billing is shut and the hourly task retries until it goes.
            # Reported as "deleting" rather than as an error: from the owner's
            # side the decision is made and acted on, just not finished yet.
            return "deleting"

    def cancel_scheduled_deletion(self, by_user=None):
        """Undo a scheduled deletion. Idempotent; returns True if one was undone."""
        if not self.is_deletion_scheduled:
            return False
        logger.info(
            "team_deletion_cancelled",
            team_id=str(self.pk),
            team_slug=self.slug,
            cancelled_by_id=str(by_user.pk) if by_user else None,
            was_scheduled_for=self.deletion_scheduled_at.isoformat(),
        )
        self.deletion_scheduled_at = None
        self.deletion_requested_at = None
        self.deletion_requested_by = None
        self.save(
            update_fields=[
                "deletion_scheduled_at",
                "deletion_requested_at",
                "deletion_requested_by",
                "updated_at",
            ]
        )
        return True


class TeamDeletionBlocked(Exception):
    """A team deletion was refused for a reason the owner has to act on."""


class TeamCleanupFailed(Exception):
    """A cleanup hook failed, so the team was kept and will be retried."""


def teams_due_for_deletion(now=None):
    """Teams whose undo window has run out. Ordered oldest request first."""
    now = now or timezone.now()
    return Team.objects.filter(
        deletion_scheduled_at__isnull=False,
        deletion_scheduled_at__lte=now,
    ).order_by("deletion_scheduled_at")


def run_team_cleanup_hooks(team):
    """Give the project a chance to tear down what the database cannot.

    A ``Team`` delete cascades every tenant ROW, and nothing else. Files in
    object storage — team logos here, and in a real product also user uploads,
    transcoded video, CDN copies, half-finished imports — survive their rows
    and are then unreachable but still billed for, and in the case of a CDN
    still publicly readable.

    The boilerplate cannot know what a project stores, so it calls out instead:
    ``SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS`` is a list of dotted paths, each a
    callable taking the team. Contract for a hook:

    * **Idempotent.** It may run again after a failure.
    * **Raise on failure.** A raising hook aborts the deletion and leaves the
      team scheduled, so the next run retries. Deleting the rows first would
      throw away the only record of what still needs cleaning.
    * **No user-facing side effects.** By the time it runs the owner has
      already been told the team is going.
    """
    from django.utils.module_loading import import_string

    for path in getattr(settings, "SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS", []):
        import_string(path)(team)


def finalize_team_deletion(team, require_due=True):
    """Actually delete a team. Idempotent and safe to retry.

    Order matters: re-check the invariant, tear down external objects, then
    delete rows. The billing re-check is not paranoia — the undo window is
    hours long, and a webhook can revive a subscription inside it.

    ``require_due`` is the guard against being called on the wrong team: the
    name says "finalize", so a caller that is not finishing a scheduled deletion
    has to say so.

    Returns True, or raises. ``TeamCleanupFailed`` when a cleanup hook fails and
    ``TeamDeletionBlocked`` when a subscription has reappeared — both so the
    caller's transaction rolls back rather than committing half a teardown, and
    so a caller that is deleting something ELSE (an account purge deleting the
    team that hangs off it) is stopped rather than left to carry on and orphan
    the team. Never returns False: "it did not happen" and "it happened" must
    not look the same to a caller that has more work queued behind it.
    """
    if require_due:
        if not team.is_deletion_scheduled:
            raise ValueError("This team is not scheduled for deletion")
        if team.deletion_scheduled_at > timezone.now():
            raise ValueError("This team is still inside its undo window")

    reason = team.deletion_blocked_reason()
    if reason:
        logger.warning(
            "team_deletion_blocked_billing",
            team_id=str(team.pk),
            team_slug=team.slug,
            deletion_scheduled_at=team.deletion_scheduled_at.isoformat()
            if team.deletion_scheduled_at
            else None,
        )
        raise TeamDeletionBlocked(reason)

    try:
        run_team_cleanup_hooks(team)
    except Exception as exc:
        # Raise, do not return False. A hook that fails half way has already
        # written to the database (a purged video deletes its row), and
        # swallowing the error here would COMMIT that half-teardown while
        # reporting "kept for retry" — the opposite of the contract. The caller
        # runs this inside a transaction, so raising rolls those writes back and
        # the retry starts from a whole team again.
        logger.error(
            "team_deletion_cleanup_failed",
            team_id=str(team.pk),
            team_slug=team.slug,
            error=str(exc),
            exc_info=True,
        )
        raise TeamCleanupFailed(str(exc)) from exc

    team_id, team_slug = str(team.pk), team.slug
    team.delete()
    logger.warning("team_deleted", team_id=team_id, team_slug=team_slug)
    return True


def delete_sole_member_teams(user):
    """Delete the teams that exist only because this user signed up.

    Registered as a ``SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS`` entry. Without
    it, purging a signup leaves its auto-provisioned team behind for good:
    ``Team`` has no foreign key to a user — membership is the only link, and
    that cascades — so the team, its projects and its uploaded objects would
    survive with nobody able to reach them.

    Only teams where this user is the **last** member are deleted. A team they
    shared with somebody else is that somebody's team now, and losing their
    membership is the whole of what should happen to it.

    Goes through ``finalize_team_deletion`` rather than ``Team.delete()``, so the
    project's cleanup hooks run and the live-subscription rule is enforced. A
    team that is still being charged therefore raises, which keeps the account
    too — deliberately: a paid team is not something to remove on a timer.
    """
    team_ids = list(
        TeamMembership.objects.filter(user=user).values_list("team_id", flat=True)
    )
    for team_id in team_ids:
        others = (
            TeamMembership.objects.filter(team_id=team_id)
            .exclude(user=user)
            .exists()
        )
        if others:
            continue
        team = Team.objects.filter(pk=team_id).first()
        if team is None:
            continue
        logger.warning(
            "team_deleted_with_purged_account",
            team_id=str(team.pk),
            team_slug=team.slug,
            user_id=str(user.pk),
        )
        finalize_team_deletion(team, require_due=False)


def get_default_team_for_user(user):
    """
    Return the first team a user has valid access to, or None.

    "Valid" mirrors the checks in TeamViewMixin: the team must be active and
    the membership must not have expired. Ordering follows TeamMembership.Meta
    (role, then created_at), so the choice is stable — "the first one we find".
    Used to redirect the personal dashboard and to build the sidebar link.
    """
    if not user.is_authenticated:
        return None
    membership = (
        TeamMembership.objects.filter(user=user, team__is_active=True)
        .filter(
            Q(access_expires_at__isnull=True)
            | Q(access_expires_at__gt=timezone.now())
        )
        .select_related("team")
        .first()
    )
    return membership.team if membership else None


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
