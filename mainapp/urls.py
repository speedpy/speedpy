from django.conf import settings
from django.urls import path
from mainapp import views
from mainapp.views import team_members
from mainapp.views import webhooks as webhook_views

urlpatterns = []

if getattr(settings, "SPEEDPY_TOURS_ENABLED", True):
    urlpatterns += [
        path('tour/complete/', views.mark_tour_complete, name='tour_complete'),
    ]

if getattr(settings, "SPEEDPY_MFA_BACKEND", "django_otp") == "django_otp":
    urlpatterns += [
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

# Team URLs (conditionally included based on SPEEDPY_TEAMS_ENABLED setting)
if getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
    urlpatterns += [
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

        # Team webhook management
        path('teams/<uuid:team_id>/webhooks/', webhook_views.TeamWebhookListView.as_view(), name='team_webhooks'),
        path('teams/<uuid:team_id>/webhooks/create/', webhook_views.TeamWebhookCreateView.as_view(), name='team_webhook_create'),
        path('teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/', webhook_views.TeamWebhookDetailView.as_view(), name='team_webhook_detail'),
        path('teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/revoke/', webhook_views.TeamWebhookRevokeView.as_view(), name='team_webhook_revoke'),
        path('teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/test/', webhook_views.TeamWebhookTestView.as_view(), name='team_webhook_test'),
        path('teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/rotate-secret/', webhook_views.TeamWebhookRotateSecretView.as_view(), name='team_webhook_rotate_secret'),
    ]

# Billing URLs (conditionally included based on SPEEDPY_BILLING_ENABLED)
if getattr(settings, "SPEEDPY_BILLING_ENABLED", False):
    # Provider webhooks — public, signature-verified, must work in BOTH modes
    # (never gated on the teams flag). Registered with and without a trailing
    # slash so APPEND_SLASH never 301-redirects a POST (which would drop the body
    # and signature).
    urlpatterns += [
        path('billing/webhooks/stripe/', views.StripeWebhookView.as_view(), name='billing_stripe_webhook'),
        path('billing/webhooks/stripe', views.StripeWebhookView.as_view()),
        path('billing/webhooks/paddle/', views.PaddleWebhookView.as_view(), name='billing_paddle_webhook'),
        path('billing/webhooks/paddle', views.PaddleWebhookView.as_view()),
    ]

    if getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
        # Team billing (owner-only)
        urlpatterns += [
            path('teams/<uuid:team_id>/billing/', views.TeamBillingView.as_view(), name='team_billing'),
            path('teams/<uuid:team_id>/billing/checkout/<str:plan_key>/<str:interval>/', views.TeamCheckoutView.as_view(), name='team_billing_checkout'),
            path('teams/<uuid:team_id>/billing/portal/', views.TeamBillingPortalView.as_view(), name='team_billing_portal'),
        ]
    else:
        # Account billing (user mode)
        urlpatterns += [
            path('accounts/billing/', views.AccountBillingView.as_view(), name='account_billing'),
            path('accounts/billing/checkout/<str:plan_key>/<str:interval>/', views.AccountCheckoutView.as_view(), name='account_billing_checkout'),
            path('accounts/billing/portal/', views.AccountBillingPortalView.as_view(), name='account_billing_portal'),
        ]