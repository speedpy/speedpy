from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.views import View
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from django.views.generic import CreateView, UpdateView

from mainapp.forms.teams import TeamCreateForm, TeamSettingsForm
from mainapp.models import Team, TeamMembership


class TeamViewMixin(LoginRequiredMixin):
    """
    Mixin for all multi-tenant views requiring team context.

    Resolves team from URL kwargs (team_id UUID or team_slug).
    Validates team is active and user has current access.
    Sets self.team and self.team_membership for child views.

    Returns 404 if:
    - Team doesn't exist or is inactive
    - User is not a team member
    - User's access has expired

    Usage:
        class MyTeamView(TeamViewMixin, TemplateView):
            template_name = 'my_template.html'
            # self.team and self.team_membership available in methods

    URL patterns supported:
        path('teams/<uuid:team_id>/.../', MyView.as_view())
        path('t/<slug:team_slug>/.../', MyView.as_view())
    """

    def dispatch(self, request, *args, **kwargs):
        """
        Override dispatch to resolve team and validate membership.
        """
        # Check if teams functionality is enabled
        if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
            raise Http404("Teams functionality is disabled")

        # Anonymous users must be sent to login BEFORE any team lookup.
        # LoginRequiredMixin cannot cover this: its check runs inside
        # super().dispatch(), which this method only calls at the end — so the
        # membership query below would run first and blow up trying to use
        # AnonymousUser as a UUID (a 500 on every team URL for logged-out
        # visitors).
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Resolve team from URL parameters
        team = self._get_team(kwargs)

        # Validate membership and access
        team_membership = self._get_membership(request.user, team)

        # Set attributes for child views
        self.team = team
        self.team_membership = team_membership

        # Permission gate: must run before the handler so no side effect
        # can execute for a user who fails the check.
        response = self.validate_team_access(request, *args, **kwargs)
        if response is not None:
            return response

        # Continue normal dispatch
        return super().dispatch(request, *args, **kwargs)

    def validate_team_access(self, request, *args, **kwargs):
        """
        Hook for permission checks that must run before the view handler.

        Called after self.team and self.team_membership are set, before
        get()/post() run. Override in subclasses to enforce role checks.

        May raise PermissionDenied/Http404, or return an HttpResponse
        (e.g. a redirect) to short-circuit dispatch. Return None to proceed.
        """
        return None

    def _get_team(self, kwargs):
        """
        Resolve team from URL kwargs (team_id or team_slug).

        Prefers team_id (UUID) over team_slug if both present.
        Returns only active teams (is_active=True).

        Raises:
            Http404: If team doesn't exist or is inactive.
        """
        team_id = kwargs.get('team_id')
        team_slug = kwargs.get('team_slug')

        try:
            if team_id:
                team = Team.objects.get(id=team_id, is_active=True)
            elif team_slug:
                team = Team.objects.get(slug=team_slug, is_active=True)
            else:
                raise Http404("No team identifier provided")
        except Team.DoesNotExist:
            raise Http404("Team not found or inactive")

        return team

    def _get_membership(self, user, team):
        """
        Validate user membership and access expiration.

        Checks:
        - User has TeamMembership for the team
        - Access has not expired (if access_expires_at is set)

        Args:
            user: The authenticated user
            team: The resolved Team instance

        Returns:
            TeamMembership instance

        Raises:
            Http404: If user is not a member or access has expired.
        """
        try:
            membership = TeamMembership.objects.get(team=team, user=user)
        except TeamMembership.DoesNotExist:
            raise Http404("User is not a member of this team")

        # Check if access has expired
        if membership.access_expires_at is not None:
            if membership.access_expires_at < timezone.now():
                raise Http404("Team access has expired")

        return membership

    def get_context_data(self, **kwargs):
        """
        Add team and user_role to template context.

        Provides:
        - team: The Team instance
        - user_role: The user's role in the team (owner/admin/member/viewer)
        """
        context = super().get_context_data(**kwargs)
        context['team'] = self.team
        context['user_role'] = self.team_membership.role
        return context


class TeamAdminRequiredMixin(TeamViewMixin):
    """
    Mixin that restricts access to team owners and admins only.

    Inherits from TeamViewMixin to get team context and membership validation.
    Adds additional check that user role is 'owner' or 'admin'.

    Returns 403 Forbidden if user is a member or viewer.

    Usage:
        class MyAdminView(TeamAdminRequiredMixin, UpdateView):
            # Only owners and admins can access
    """

    def validate_team_access(self, request, *args, **kwargs):
        """
        Check admin privileges before the view handler runs.
        """
        response = super().validate_team_access(request, *args, **kwargs)
        if response is not None:
            return response

        if self.team_membership.role not in ['owner', 'admin']:
            raise PermissionDenied("Only team owners and admins can access this page")

        return None


class TeamCreateView(LoginRequiredMixin, CreateView):
    model = Team
    template_name = "mainapp/teams/team_create.html"
    object: Team
    form_class = TeamCreateForm

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
            raise Http404("Teams functionality is disabled")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('team_dashboard', kwargs={'team_id': self.object.pk})

    def form_valid(self, form):
        self.object = form.save()
        TeamMembership.objects.create(
            team=self.object,
            user=self.request.user,
            role="owner",
        )
        return HttpResponseRedirect(self.get_success_url())


class TeamSettingsView(TeamAdminRequiredMixin, UpdateView):
    """
    View for updating team settings (owner/admin only).

    Allows owners and admins to update team name, slug, and logo.
    Access is restricted by TeamAdminRequiredMixin.
    """
    model = Team
    form_class = TeamSettingsForm
    template_name = "mainapp/teams/settings.html"

    def get_object(self, queryset=None):
        """Return the team from TeamViewMixin context."""
        return self.team

    def get_context_data(self, **kwargs):
        """Add what the danger zone needs to describe itself.

        The copy beside the delete button has to match the configured delay, so
        the number reaches the template rather than being duplicated there.
        """
        context = super().get_context_data(**kwargs)
        context["team_deletion_delay_hours"] = Team.deletion_delay_hours()
        context["team_deletion_blocked_reason"] = self.team.deletion_blocked_reason()
        return context

    def get_success_url(self):
        """Redirect back to settings page after successful update."""
        messages.success(self.request, "Team settings updated successfully!")
        return reverse('team_settings', kwargs={'team_id': self.team.pk})

    def form_invalid(self, form):
        """Add error message on form validation failure."""
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class TeamOwnerRequiredMixin(TeamViewMixin):
    """
    Mixin that restricts access to team owners only.

    Deliberately narrower than TeamAdminRequiredMixin: an admin may manage a
    team, but ending it is the owner's decision. Any current owner qualifies —
    a team can have several, and each already has the power to schedule a
    deletion, so refusing one the right to undo another's would be theatre.
    """

    def validate_team_access(self, request, *args, **kwargs):
        response = super().validate_team_access(request, *args, **kwargs)
        if response is not None:
            return response

        if self.team_membership.role != "owner":
            raise PermissionDenied("Only team owners can delete a team")

        return None


class TeamDeleteView(TeamOwnerRequiredMixin, View):
    """
    Delete the team, or schedule the deletion, depending on
    SPEEDPY_TEAM_DELETION_DELAY_HOURS. POST only: this is not a safe method,
    and a GET that deletes a tenant would be deleted by a link prefetcher.
    """

    def post(self, request, *args, **kwargs):
        from mainapp.models import TeamDeletionBlocked

        try:
            outcome = self.team.request_deletion(by_user=request.user)
        except TeamDeletionBlocked as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(
                reverse("team_settings", kwargs={"team_id": self.team.pk})
            )

        if outcome == "deleted":
            messages.success(request, f"Team “{self.team.name}” has been deleted.")
            return HttpResponseRedirect(reverse("dashboard"))

        if outcome == "already_scheduled":
            messages.info(request, "This team is already scheduled for deletion.")
        else:
            messages.warning(
                request,
                "This team is scheduled for deletion. You can undo it from this "
                "page until then.",
            )
        return HttpResponseRedirect(
            reverse("team_settings", kwargs={"team_id": self.team.pk})
        )


class TeamDeleteCancelView(TeamOwnerRequiredMixin, View):
    """Undo a scheduled deletion. POST only, owner only, idempotent."""

    def post(self, request, *args, **kwargs):
        if self.team.cancel_scheduled_deletion(by_user=request.user):
            messages.success(request, "The scheduled deletion has been cancelled.")
        else:
            messages.info(request, "This team was not scheduled for deletion.")
        return HttpResponseRedirect(
            reverse("team_settings", kwargs={"team_id": self.team.pk})
        )
