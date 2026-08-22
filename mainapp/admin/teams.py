from django.contrib import admin
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

    def delete_model(self, request, obj):
        from mainapp.models.teams import finalize_team_deletion

        finalize_team_deletion(obj, require_due=False)

    def delete_queryset(self, request, queryset):
        from mainapp.models.teams import finalize_team_deletion

        # One at a time on purpose: a bulk delete cannot run per-team cleanup,
        # and it would skip the subscription check.
        for team in queryset:
            finalize_team_deletion(team, require_due=False)


admin.site.register(Team, TeamAdmin)


class TeamMembershipAdmin(admin.ModelAdmin):
    raw_id_fields = ('team', 'user', 'invited_by')

    pass


admin.site.register(TeamMembership, TeamMembershipAdmin)


class TeamInvitationAdmin(admin.ModelAdmin):
    raw_id_fields = ('team', 'user', 'invited_by',)
    pass


admin.site.register(TeamInvitation, TeamInvitationAdmin)
