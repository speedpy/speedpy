from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

User = get_user_model()

TOKEN_URL = "/api/auth/token/"


def _create_user(email="test@example.com", password="testpass123", verified=False):
    user = User.objects.create_user(email=email, password=password)
    EmailAddress.objects.create(
        user=user, email=email, primary=True, verified=verified
    )
    return user


class EmailSyncSignalTests(TestCase):
    def test_email_sync_on_verify(self):
        user = User.objects.create_user(email="sync@example.com", password="pass123")
        self.assertFalse(user.is_email_confirmed)
        EmailAddress.objects.create(
            user=user, email="sync@example.com", primary=True, verified=True
        )
        user.refresh_from_db()
        self.assertTrue(user.is_email_confirmed)

    def test_email_sync_on_unverify(self):
        user = User.objects.create_user(
            email="sync2@example.com", password="pass123", is_email_confirmed=True
        )
        ea = EmailAddress.objects.create(
            user=user, email="sync2@example.com", primary=True, verified=True
        )
        user.refresh_from_db()
        self.assertTrue(user.is_email_confirmed)

        ea.verified = False
        ea.save()
        user.refresh_from_db()
        self.assertFalse(user.is_email_confirmed)

    def test_non_primary_email_does_not_sync(self):
        user = User.objects.create_user(email="sync3@example.com", password="pass123")
        EmailAddress.objects.create(
            user=user, email="secondary@example.com", primary=False, verified=True
        )
        user.refresh_from_db()
        self.assertFalse(user.is_email_confirmed)

    def test_email_sync_on_delete(self):
        user = User.objects.create_user(email="sync4@example.com", password="pass123")
        ea = EmailAddress.objects.create(
            user=user, email="sync4@example.com", primary=True, verified=True
        )
        user.refresh_from_db()
        self.assertTrue(user.is_email_confirmed)

        ea.delete()
        user.refresh_from_db()
        self.assertFalse(user.is_email_confirmed)


class JWTEmailGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_jwt_blocked_when_email_unverified(self):
        _create_user(verified=False)
        response = self.client.post(
            TOKEN_URL,
            {"email": "test@example.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("not verified", response.data["detail"].lower())

    def test_jwt_allowed_when_email_verified(self):
        _create_user(verified=True)
        response = self.client.post(
            TOKEN_URL,
            {"email": "test@example.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    @override_settings(SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL=False)
    def test_jwt_allowed_when_gate_disabled(self):
        _create_user(verified=False)
        response = self.client.post(
            TOKEN_URL,
            {"email": "test@example.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)


class JWTMFAGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(verified=True)

    @override_settings(SPEEDPY_MFA_BACKEND="allauth_mfa")
    def test_jwt_mfa_required_when_totp_enrolled(self):
        with patch("usermodel.api.user_has_totp", return_value=True):
            response = self.client.post(
                TOKEN_URL,
                {"email": "test@example.com", "password": "testpass123"},
                format="json",
            )
        self.assertEqual(response.status_code, 401)
        self.assertIn("mfa code is required", response.data["detail"].lower())

    @override_settings(SPEEDPY_MFA_BACKEND="allauth_mfa")
    def test_jwt_mfa_valid_totp_allows_token(self):
        with patch("usermodel.api.user_has_totp", return_value=True), \
             patch("usermodel.api.verify_totp", return_value=True):
            response = self.client.post(
                TOKEN_URL,
                {
                    "email": "test@example.com",
                    "password": "testpass123",
                    "mfa_code": "123456",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    @override_settings(SPEEDPY_MFA_BACKEND="allauth_mfa")
    def test_jwt_mfa_invalid_totp_blocked(self):
        with patch("usermodel.api.user_has_totp", return_value=True), \
             patch("usermodel.api.verify_totp", return_value=False):
            response = self.client.post(
                TOKEN_URL,
                {
                    "email": "test@example.com",
                    "password": "testpass123",
                    "mfa_code": "000000",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid mfa code", response.data["detail"].lower())

    def test_jwt_no_mfa_code_when_no_totp_ignored(self):
        """User without TOTP can obtain tokens without mfa_code."""
        response = self.client.post(
            TOKEN_URL,
            {"email": "test@example.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    @override_settings(SPEEDPY_JWT_REQUIRE_MFA=False)
    def test_jwt_mfa_gate_disabled(self):
        """When SPEEDPY_JWT_REQUIRE_MFA=False, MFA is not checked even if enrolled."""
        # user_has_totp returns False when setting is disabled, so tokens are issued.
        response = self.client.post(
            TOKEN_URL,
            {"email": "test@example.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)


class PATEmailGateTests(TestCase):
    def setUp(self):
        self.user = _create_user(email="pat@example.com", password="patpass123", verified=False)
        self.client.login(email="pat@example.com", password="patpass123")

    def test_pat_ui_blocked_when_email_unverified(self):
        response = self.client.post(
            "/accounts/tokens/create/",
            {"name": "test-token", "scopes": []},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/email/", response.url)


class PATReauthGateTests(TestCase):
    def setUp(self):
        self.user = _create_user(email="pat2@example.com", password="patpass123", verified=True)
        self.client.login(email="pat2@example.com", password="patpass123")

    def test_pat_ui_redirects_when_reauth_missing(self):
        with patch(
            "allauth.account.internal.flows.reauthentication.did_recently_authenticate", return_value=False
        ):
            response = self.client.post(
                "/accounts/tokens/create/",
                {"name": "test-token", "scopes": []},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/reauthenticate/", response.url)

    def test_pat_ui_creates_token_after_reauth(self):
        with patch(
            "allauth.account.internal.flows.reauthentication.did_recently_authenticate", return_value=True
        ):
            response = self.client.post(
                "/accounts/tokens/create/",
                {"name": "test-token"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/tokens/", response.url)
        from usermodel.models import PersonalAccessToken

        self.assertTrue(
            PersonalAccessToken.objects.filter(user=self.user, name="test-token").exists()
        )

    @override_settings(SPEEDPY_PAT_REQUIRE_RECENT_REAUTH=False)
    def test_pat_reauth_gate_disabled(self):
        response = self.client.post(
            "/accounts/tokens/create/",
            {"name": "no-reauth-token"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/tokens/", response.url)
        from usermodel.models import PersonalAccessToken

        self.assertTrue(
            PersonalAccessToken.objects.filter(
                user=self.user, name="no-reauth-token"
            ).exists()
        )


class SettingsDisableAllGatesTests(TestCase):
    """Verify all gates can be disabled via settings."""

    @override_settings(
        SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL=False,
        SPEEDPY_JWT_REQUIRE_MFA=False,
    )
    def test_settings_can_disable_jwt_gates(self):
        client = APIClient()
        # No verified email, no MFA — should still issue tokens.
        user = User.objects.create_user(email="nogate@example.com", password="pass123")
        response = client.post(
            TOKEN_URL,
            {"email": "nogate@example.com", "password": "pass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
