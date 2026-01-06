from functools import partial

from celery import current_app
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import ListView, FormView, TemplateView, View
from django.contrib.auth import get_user_model
from django.db import transaction
from mainapp.forms.teams import InviteMemberForm, UpdateMemberRoleForm
from mainapp.models import Team, TeamMembership, TeamInvitation
from mainapp.views.teams import TeamViewMixin, TeamAdminRequiredMixin

User = get_user_model()


class TeamMembersListView(TeamViewMixin, ListView):
    """
    List all active team members and pending invitations.

    Accessible to all team members (owner/admin/member/viewer).
    Pending invitations only visible to owners and admins.
    """
    template_name = 'mainapp/teams/members/list.html'
    context_object_name = 'members'

    def get_queryset(self):
        """Get all active members for this team"""
        return self.team.get_members()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add pending invitations (only for owner/admin)
        if self.team_membership.role in ['owner', 'admin']:
            context['pending_invitations'] = self.team.get_invitations()
        else:
            context['pending_invitations'] = []

        # Add permission info for template
        context['can_invite'] = self.team_membership.role in ['owner', 'admin']

        return context


class InviteMemberView(TeamAdminRequiredMixin, FormView):
    """
    Send invitation to a new team member (owner/admin only).

    Supports inviting existing users or new users via email.
    """
    template_name = 'mainapp/teams/members/invite.html'
    form_class = InviteMemberForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['team'] = self.team
        kwargs['inviter_membership'] = self.team_membership
        return kwargs

    def form_valid(self, form):
        email = form.cleaned_data['email']
        role = form.cleaned_data['role']
        message = form.cleaned_data['message']

        # Check if inviter can invite this role
        if not self.team_membership.can_invite_role(role):
            messages.error(self.request, f"You don't have permission to invite {role}s")
            return self.form_invalid(form)

        # Check if user exists
        user = User.objects.filter(email=email).first()

        # Create invitation
        invitation = TeamInvitation.objects.create(
            team=self.team,
            invited_by=self.request.user,
            email=email,
            user=user,
            role=role,
            message=message
        )
        transaction.on_commit(
            partial(
                current_app.send_task,
                "send_team_invitation_email",
                kwargs={"invitation_id": invitation.pk}
            )
        )

        messages.success(
            self.request,
            f"Invitation sent to {email}"
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('team_members', kwargs={'team_id': self.team.pk})


class AcceptInvitationView(LoginRequiredMixin, TemplateView):
    """
    Accept a team invitation via token.

    Accessible to any logged-in user with a valid invitation token.
    """
    template_name = 'mainapp/teams/members/accept.html'

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
            raise Http404("Teams functionality is disabled")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        token = self.kwargs['token']

        try:
            invitation = TeamInvitation.objects.select_related(
                'team', 'invited_by'
            ).get(token=token)
            context['invitation'] = invitation
            context['is_valid'] = invitation.is_valid()
        except TeamInvitation.DoesNotExist:
            context['invitation'] = None
            context['is_valid'] = False

        return context

    def post(self, request, *args, **kwargs):
        token = self.kwargs['token']

        try:
            invitation = TeamInvitation.objects.get(token=token)

            # Accept the invitation
            membership = invitation.accept(request.user)

            messages.success(
                request,
                f"Welcome to {invitation.team.name}! You've been added as a {membership.get_role_display()}."
            )
            return redirect('team_dashboard', team_id=invitation.team.pk)

        except TeamInvitation.DoesNotExist:
            messages.error(request, "Invitation not found")
            return redirect('dashboard')
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('dashboard')


class DeclineInvitationView(View):
    """
    Decline a team invitation via token.

    No login required - public endpoint.
    """

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
            raise Http404("Teams functionality is disabled")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        token = self.kwargs['token']

        try:
            invitation = TeamInvitation.objects.get(token=token)
            invitation.decline()

            messages.info(request, f"You've declined the invitation to join {invitation.team.name}")
        except TeamInvitation.DoesNotExist:
            messages.error(request, "Invitation not found")

        # Redirect to login page or home
        return redirect('dashboard')


class UpdateMemberRoleView(TeamAdminRequiredMixin, TeamViewMixin, FormView):
    """
    Update a team member's role (owner/admin with restrictions).

    - Owners can change any role
    - Admins can only change member/viewer roles
    """
    template_name = 'mainapp/teams/members/update_role.html'
    form_class = UpdateMemberRoleForm
    target_membership = None

    def dispatch(self, request, *args, **kwargs):
        # Get the membership being updated
        response = super().dispatch(request, *args, **kwargs)

        # Check if current user can manage this member
        if not self.team_membership.can_manage_member(self.target_membership):
            raise PermissionDenied("You don't have permission to manage this member")

        # Prevent changing own role
        if self.target_membership.user == request.user:
            messages.error(request, "You cannot change your own role")
            return redirect('team_members', team_id=self.team.pk)

        return response

    def get_target_membership(self):
        if self.target_membership:
            return self.target_membership
        membership_id = self.kwargs.get('membership_id')
        self.target_membership = get_object_or_404(
            TeamMembership.objects.select_related('user'),
            pk=membership_id,
            team=self.team
        )
        return self.target_membership

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['membership'] = self.get_target_membership()
        kwargs['current_user_membership'] = self.team_membership
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['target_membership'] = self.get_target_membership()
        return context

    def form_valid(self, form):
        new_role = form.cleaned_data['role']
        old_role = self.get_target_membership().role

        # Prevent demoting last owner
        if old_role == 'owner' and new_role != 'owner':
            owner_count = TeamMembership.objects.filter(
                team=self.team,
                role='owner'
            ).count()
            if owner_count <= 1:
                messages.error(self.request, "Cannot change the last owner's role")
                return self.form_invalid(form)

        # Update role
        self.target_membership.role = new_role
        self.target_membership.save()
        transaction.on_commit(
            partial(
                current_app.send_task,
                "send_role_change_email",
                kwargs={
                    "membership_id": self.target_membership.pk, "old_role": old_role, "new_role": new_role
                }
            )
        )

        messages.success(
            self.request,
            f"Updated {self.target_membership.user.email}'s role to {new_role}"
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('team_members', kwargs={'team_id': self.team.pk})


class RemoveMemberView(TeamAdminRequiredMixin, View):
    """
    Remove a member from the team (owner/admin with restrictions).

    - Owners can remove anyone
    - Admins can only remove members/viewers
    - Cannot remove self
    - Cannot remove last owner
    """

    def post(self, request, *args, **kwargs):
        membership_id = self.kwargs.get('membership_id')
        target_membership = get_object_or_404(
            TeamMembership.objects.select_related('user'),
            pk=membership_id,
            team=self.team
        )

        # Check if current user can manage this member
        if not self.team_membership.can_manage_member(target_membership):
            messages.error(request, "You don't have permission to remove this member")
            return redirect('team_members', team_id=self.team.pk)

        # Prevent self-removal
        if target_membership.user == request.user:
            messages.error(request, "You cannot remove yourself from the team")
            return redirect('team_members', team_id=self.team.pk)

        # Prevent removing last owner
        if target_membership.role == 'owner':
            owner_count = TeamMembership.objects.filter(
                team=self.team,
                role='owner'
            ).count()
            if owner_count <= 1:
                messages.error(request, "Cannot remove the last owner")
                return redirect('team_members', team_id=self.team.pk)

        # Remove the member
        user_email = target_membership.user.email
        target_membership.delete()

        messages.success(request, f"Removed {user_email} from the team")
        return redirect('team_members', team_id=self.team.pk)


class RevokeInvitationView(TeamAdminRequiredMixin, View):
    """
    Revoke a pending invitation (owner/admin only).
    """

    def post(self, request, *args, **kwargs):
        invitation_id = self.kwargs.get('invitation_id')
        invitation = get_object_or_404(
            TeamInvitation,
            pk=invitation_id,
            team=self.team
        )

        # Check if invitation can be revoked
        if invitation.status != 'pending':
            messages.error(request, "This invitation cannot be revoked")
            return redirect('team_members', team_id=self.team.pk)

        # Revoke the invitation
        invitation.revoke()

        messages.success(request, f"Revoked invitation to {invitation.email}")
        return redirect('team_members', team_id=self.team.pk)
