from .welcome import WelcomeToSpeedPyView, PricingView
from .dashboard import DashboardView
from .otp_views import (
    OTPSetupView,
    OTPVerifySetupView,
    OTPBackupCodesView,
    OTPDisableView,
    OTPRegenerateBackupCodesView,
    OTPSettingsView,
    OTPLoginView,
)

__all__ = [
    "WelcomeToSpeedPyView",
    "PricingView",
    "DashboardView",
    "OTPSetupView",
    "OTPVerifySetupView",
    "OTPBackupCodesView",
    "OTPDisableView",
    "OTPRegenerateBackupCodesView",
    "OTPSettingsView",
    "OTPLoginView",
]
