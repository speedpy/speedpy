from django.conf import settings as django_settings

from .welcome import WelcomeToSpeedPyView, PricingView
from .contact import ContactView
from .dashboard import DashboardView
from .speedpyui_preview import SpeedpyuiFormViewExampleView, SpeedpyuiPreviewView
from .tour_views import mark_tour_complete
from .teams import TeamViewMixin, TeamCreateView, TeamAdminRequiredMixin, TeamSettingsView
from .teams_dashboard import TeamDashboardView
from . import team_members

__all__ = [
    "WelcomeToSpeedPyView",
    "PricingView",
    "ContactView",
    "DashboardView",
    "SpeedpyuiPreviewView",
    "SpeedpyuiFormViewExampleView",
    "mark_tour_complete",
    "TeamViewMixin",
    "TeamAdminRequiredMixin",
    "TeamDashboardView",
    "TeamCreateView",
    "TeamSettingsView",
    "team_members",
]

if getattr(django_settings, "SPEEDPY_MFA_BACKEND", "django_otp") == "django_otp":
    from .otp_views import (
        OTPSetupView,
        OTPVerifySetupView,
        OTPBackupCodesView,
        OTPDisableView,
        OTPRegenerateBackupCodesView,
        OTPSettingsView,
        OTPLoginView,
    )
    __all__ += [
        "OTPSetupView",
        "OTPVerifySetupView",
        "OTPBackupCodesView",
        "OTPDisableView",
        "OTPRegenerateBackupCodesView",
        "OTPSettingsView",
        "OTPLoginView",
    ]
