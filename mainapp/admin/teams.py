from django.contrib import admin
from mainapp.models import Team, TeamMembership, TeamInvitation


class TeamAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    pass


admin.site.register(Team, TeamAdmin)


class TeamMembershipAdmin(admin.ModelAdmin):
    raw_id_fields = ('team', 'user', 'invited_by')

    pass


admin.site.register(TeamMembership, TeamMembershipAdmin)


class TeamInvitationAdmin(admin.ModelAdmin):
    raw_id_fields = ('team', 'user', 'invited_by',)
    pass


admin.site.register(TeamInvitation, TeamInvitationAdmin)
