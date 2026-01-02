from django.urls import path
from mainapp import views

urlpatterns = [
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