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

        LoginRequiredMixin already ensures request.user is authenticated.
        """
        # Resolve team from URL parameters
        team = self._get_team(kwargs)

        # Validate membership and access
        team_membership = self._get_membership(request.user, team)

        # Set attributes for child views
        self.team = team
        self.team_membership = team_membership

        # Continue normal dispatch
        return super().dispatch(request, *args, **kwargs)

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

    def dispatch(self, request, *args, **kwargs):
        """
        Override dispatch to check admin privileges after team validation.
        """
        # Get team and membership from parent TeamViewMixin
        response = super().dispatch(request, *args, **kwargs)

        # Check if user has admin privileges
        if self.team_membership.role not in ['owner', 'admin']:
            raise PermissionDenied("Only team owners and admins can access this page")

        return response


class TeamCreateView(LoginRequiredMixin, CreateView):
    model = Team
    template_name = "mainapp/teams/team_create.html"
    object: Team
    form_class = TeamCreateForm

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

    def get_success_url(self):
        """Redirect back to settings page after successful update."""
        messages.success(self.request, "Team settings updated successfully!")
        return reverse('team_settings', kwargs={'team_id': self.team.pk})

    def form_invalid(self, form):
        """Add error message on form validation failure."""
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)
