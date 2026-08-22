from django.contrib import admin, messages
from mainapp.models import Team, TeamMembership, TeamInvitation


class TeamAdmin(admin.ModelAdmin):
    """Team admin, with deletion routed through the deletion service.

    Django's admin deletes in two different ways, and both had to be closed.
    The single-object delete calls ``Model.delete()``, which enforces the
    live-subscription rule but runs no cleanup hooks, so it left the team's
    objects in storage. The bulk action calls ``QuerySet.delete()``, which the
    collector performs without ever calling ``Model.delete()`` — so it bypassed
    the subscription rule as well, and staff could delete a team the provider
    was still charging.
    """

    prepopulated_fields = {'slug': ('name',)}

    def _delete(self, request, team):
        """Delete one team, reporting a refusal instead of raising a 500."""
        from mainapp.models.teams import (
            TeamCleanupFailed,
            TeamDeletionBlocked,
            finalize_team_deletion,
        )

        try:
            finalize_team_deletion(team, require_due=False)
        except (TeamDeletionBlocked, TeamCleanupFailed) as exc:
            self.message_user(
                request, f"{team.name}: {exc}", level=messages.ERROR
            )
            return False
        return True

    def delete_model(self, request, obj):
        self._delete(request, obj)

    def delete_queryset(self, request, queryset):
        # One at a time on purpose: a bulk delete cannot run per-team cleanup,
        # and it would skip the subscription check.
        for team in queryset:
            self._delete(request, team)


admin.site.register(Team, TeamAdmin)


class TeamMembershipAdmin(admin.ModelAdmin):
    raw_id_fields = ('team', 'user', 'invited_by')

    pass


admin.site.register(TeamMembership, TeamMembershipAdmin)


class TeamInvitationAdmin(admin.ModelAdmin):
    raw_id_fields = ('team', 'user', 'invited_by',)
    pass


admin.site.register(TeamInvitation, TeamInvitationAdmin)
