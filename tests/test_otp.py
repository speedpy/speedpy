"""
Tests for OTP management views.

Skipped (require complex session state):
- OTPLoginView  – needs 'otp_pre_auth_user_id' session key set by login flow
- OTPVerifySetupView – POST-only meaningful path; GET just renders the same setup template
- OTPRegenerateBackupCodesView – POST only
"""
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_otp_settings_requires_login(client):
    response = client.get(reverse("account_otp_settings"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_otp_settings(auth_client):
    response = auth_client.get(reverse("account_otp_settings"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_otp_setup_requires_login(client):
    response = client.get(reverse("account_otp_setup"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_otp_setup(auth_client):
    """OTPSetupView creates an unconfirmed TOTP device and renders the QR page."""
    response = auth_client.get(reverse("account_otp_setup"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_otp_backup_codes_requires_login(client):
    response = client.get(reverse("account_otp_backup_codes"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_otp_backup_codes(auth_client):
    """OTPBackupCodesView renders even when no backup codes exist yet."""
    response = auth_client.get(reverse("account_otp_backup_codes"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_otp_disable_requires_login(client):
    response = client.get(reverse("account_otp_disable"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_otp_disable(auth_client):
    response = auth_client.get(reverse("account_otp_disable"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_otp_login_redirects_without_session(client):
    """OTPLoginView redirects to login when the pre-auth session key is absent."""
    response = client.get(reverse("account_login_otp"))
    # Should redirect (not 200 and not 500)
    assert response.status_code == 302
