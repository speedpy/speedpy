from django.urls import path
from mainapp import views
from mainapp.views import team_members

urlpatterns = [
    path('teams/create/', views.TeamCreateView.as_view(), name='team_create'),
    path('teams/<uuid:team_id>/dashboard/', views.TeamDashboardView.as_view(), name='team_dashboard'),
    path('teams/<uuid:team_id>/settings/', views.TeamSettingsView.as_view(), name='team_settings'),

    # Team member management
    path('teams/<uuid:team_id>/members/', team_members.TeamMembersListView.as_view(), name='team_members'),
    path('teams/<uuid:team_id>/members/invite/', team_members.InviteMemberView.as_view(), name='invite_member'),
    path('teams/<uuid:team_id>/members/<uuid:membership_id>/update-role/', team_members.UpdateMemberRoleView.as_view(), name='update_member_role'),
    path('teams/<uuid:team_id>/members/<uuid:membership_id>/remove/', team_members.RemoveMemberView.as_view(), name='remove_member'),

    # Public invitation URLs (with token)
    path('teams/invitations/<str:token>/accept/', team_members.AcceptInvitationView.as_view(), name='accept_invitation'),
    path('teams/invitations/<str:token>/decline/', team_members.DeclineInvitationView.as_view(), name='decline_invitation'),
    path('teams/<uuid:team_id>/invitations/<uuid:invitation_id>/revoke/', team_members.RevokeInvitationView.as_view(), name='revoke_invitation'),

    #path('t/<slug:team_slug>/dashboard/', TeamDashboardView.as_view(), name='team_dashboard_slug'),
    # OTP Management URLs
    path('accounts/otp/settings/', views.OTPSettingsView.as_view(), name='account_otp_settings'),
    path('accounts/otp/setup/', views.OTPSetupView.as_view(), name='account_otp_setup'),
    path('accounts/otp/verify-setup/', views.OTPVerifySetupView.as_view(), name='account_otp_verify_setup'),
    path('accounts/otp/backup-codes/', views.OTPBackupCodesView.as_view(), name='account_otp_backup_codes'),
    path('accounts/otp/disable/', views.OTPDisableView.as_view(), name='account_otp_disable'),
    path('accounts/otp/regenerate-backup-codes/', views.OTPRegenerateBackupCodesView.as_view(), name='account_otp_regenerate_backup_codes'),

    # OTP Login URL
    path('accounts/login/otp/', views.OTPLoginView.as_view(), name='account_login_otp'),
]