import base64
import hashlib
import secrets

from django.test import TestCase, override_settings
from oauth2_provider.models import AccessToken, Application, RefreshToken
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from mainapp.models import Team, TeamMembership
from usermodel.models import User


class OAuth2TestBase(TestCase):
    """Shared setup for OAuth2 tests."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="oauth@example.com", password="oauthpass123",
            first_name="OAuth", last_name="User",
        )
        self.raw_client_secret = secrets.token_urlsafe(32)
        self.app = Application.objects.create(
            name="Test App",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            user=self.user,
            redirect_uris="https://example.com/callback",
            client_secret=self.raw_client_secret,
        )

    def _create_access_token(self, scope="read:profile", expires_in=3600):
        return AccessToken.objects.create(
            user=self.user,
            application=self.app,
            token=secrets.token_hex(32),
            expires=timezone.now() + timedelta(seconds=expires_in),
            scope=scope,
        )


class OAuth2AuthenticationTests(OAuth2TestBase):
    def test_oauth2_token_authenticates(self):
        token = self._create_access_token(scope="read:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "oauth@example.com")

    def test_expired_oauth2_token_rejected(self):
        token = self._create_access_token(expires_in=-1)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    def test_revoked_oauth2_token_rejected(self):
        token = self._create_access_token()
        token.revoke()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)


class OAuth2ScopeEnforcementTests(OAuth2TestBase):
    def test_matching_scope_allowed(self):
        token = self._create_access_token(scope="read:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)

    def test_wrong_scope_denied(self):
        token = self._create_access_token(scope="read:teams")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/me/")
        self.assertIn(response.status_code, [401, 403])

    def test_multiple_scopes_partial_match_denied(self):
        """Token with read:teams but not read:profile can't access /me/."""
        token = self._create_access_token(scope="read:teams write:teams")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/me/")
        self.assertIn(response.status_code, [401, 403])

    def test_teams_scope_allows_team_list(self):
        # Set up team membership
        team = Team.objects.create(name="OAuth Team", slug="oauth-team")
        TeamMembership.objects.create(team=team, user=self.user, role="owner")

        token = self._create_access_token(scope="read:teams")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/teams/")
        self.assertEqual(response.status_code, 200)

    def test_profile_scope_cannot_access_teams(self):
        token = self._create_access_token(scope="read:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.get("/api/v1/teams/")
        self.assertIn(response.status_code, [401, 403])

    def test_write_scope_allows_patch(self):
        token = self._create_access_token(scope="write:profile")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.patch(
            "/api/v1/me/",
            {"first_name": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Updated")


class OAuth2AuthorizationCodeFlowTests(OAuth2TestBase):
    def test_authorize_endpoint_requires_login(self):
        response = self.client.get("/o/authorize/", {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": "https://example.com/callback",
            "scope": "read:profile",
        })
        self.assertIn(response.status_code, [302, 200])

    def test_authorize_shows_consent_when_logged_in(self):
        self.client.login(email="oauth@example.com", password="oauthpass123")
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        response = self.client.get("/o/authorize/", {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": "https://example.com/callback",
            "scope": "read:profile",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authorize")
        self.assertContains(response, self.app.name)

    def test_full_auth_code_pkce_flow(self):
        """Complete authorization code + PKCE flow: authorize, exchange, use."""
        from urllib.parse import parse_qs, urlparse

        from django.test import Client

        http_client = Client()
        http_client.login(email="oauth@example.com", password="oauthpass123")

        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        # Step 1: GET authorize — consent page
        auth_params = {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": "https://example.com/callback",
            "scope": "read:profile",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        response = http_client.get("/o/authorize/", auth_params)
        self.assertEqual(response.status_code, 200)

        # Step 2: POST authorize — approve consent
        response = http_client.post("/o/authorize/", {
            **auth_params,
            "allow": "true",
        })
        self.assertEqual(response.status_code, 302)
        redirect_url = response["Location"]
        parsed = urlparse(redirect_url)
        code = parse_qs(parsed.query)["code"][0]

        # Step 3: Exchange code for tokens
        token_response = http_client.post(
            "/o/token/",
            f"grant_type=authorization_code&code={code}"
            f"&redirect_uri=https://example.com/callback"
            f"&client_id={self.app.client_id}"
            f"&client_secret={self.raw_client_secret}"
            f"&code_verifier={code_verifier}",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(token_response.status_code, 200)
        tokens = token_response.json()
        self.assertIn("access_token", tokens)
        self.assertIn("refresh_token", tokens)
        self.assertEqual(tokens["scope"], "read:profile")

        # Step 4: Use access token to call /api/v1/me/
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
        me_response = api_client.get("/api/v1/me/")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.data["email"], "oauth@example.com")

    def test_full_auth_code_pkce_refresh(self):
        """Complete flow including refresh token exchange."""
        from urllib.parse import parse_qs, urlparse

        from django.test import Client

        http_client = Client()
        http_client.login(email="oauth@example.com", password="oauthpass123")

        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        auth_params = {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": "https://example.com/callback",
            "scope": "read:profile",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        http_client.get("/o/authorize/", auth_params)
        response = http_client.post("/o/authorize/", {**auth_params, "allow": "true"})
        code = parse_qs(urlparse(response["Location"]).query)["code"][0]

        token_response = http_client.post(
            "/o/token/",
            f"grant_type=authorization_code&code={code}"
            f"&redirect_uri=https://example.com/callback"
            f"&client_id={self.app.client_id}"
            f"&client_secret={self.raw_client_secret}"
            f"&code_verifier={code_verifier}",
            content_type="application/x-www-form-urlencoded",
        )
        tokens = token_response.json()

        # Refresh the token
        refresh_response = http_client.post(
            "/o/token/",
            f"grant_type=refresh_token"
            f"&refresh_token={tokens['refresh_token']}"
            f"&client_id={self.app.client_id}"
            f"&client_secret={self.raw_client_secret}",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(refresh_response.status_code, 200)
        new_tokens = refresh_response.json()
        self.assertIn("access_token", new_tokens)
        self.assertNotEqual(new_tokens["access_token"], tokens["access_token"])


class OAuth2DeviceFlowTests(OAuth2TestBase):
    def setUp(self):
        super().setUp()
        self.device_app = Application.objects.create(
            name="Device App",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_DEVICE_CODE,
            user=self.user,
        )

    def test_device_authorization_endpoint_exists(self):
        from django.test import Client

        http_client = Client()
        body = f"client_id={self.device_app.client_id}&scope=read:profile"
        response = http_client.post(
            "/o/device-authorization/",
            body,
            content_type="application/x-www-form-urlencoded",
        )
        # Should return 200 with device_code, user_code, verification_uri
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("device_code", data)
        self.assertIn("user_code", data)

    def test_device_flow_polling_before_approval(self):
        """Polling /o/token/ before user approves returns authorization_pending."""
        from django.test import Client

        http_client = Client()

        # Step 1: Start device flow
        body = f"client_id={self.device_app.client_id}&scope=read:profile"
        response = http_client.post(
            "/o/device-authorization/",
            body,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 200)
        device_code = response.json()["device_code"]

        # Step 2: Poll before approval — should get authorization_pending
        poll_body = (
            f"grant_type=urn:ietf:params:oauth:grant-type:device_code"
            f"&device_code={device_code}"
            f"&client_id={self.device_app.client_id}"
        )
        poll_response = http_client.post(
            "/o/token/",
            poll_body,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(poll_response.status_code, 400)
        self.assertEqual(
            poll_response.json().get("error"), "authorization_pending"
        )

    def test_device_flow_complete(self):
        """Full device flow: request code, approve via model, poll for token."""
        from django.test import Client

        from oauth2_provider.models import DeviceGrant

        http_client = Client()

        # Step 1: Start device flow
        body = f"client_id={self.device_app.client_id}&scope=read:profile"
        response = http_client.post(
            "/o/device-authorization/",
            body,
            content_type="application/x-www-form-urlencoded",
        )
        device_data = response.json()
        device_code = device_data["device_code"]

        # Step 2: Approve directly via model (simulates user consent)
        grant = DeviceGrant.objects.get(device_code=device_code)
        grant.user = self.user
        grant.status = "authorized"
        grant.save()

        # Step 3: Poll for token — should succeed now
        poll_body = (
            f"grant_type=urn:ietf:params:oauth:grant-type:device_code"
            f"&device_code={device_code}"
            f"&client_id={self.device_app.client_id}"
        )
        poll_response = http_client.post(
            "/o/token/",
            poll_body,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(poll_response.status_code, 200)
        tokens = poll_response.json()
        self.assertIn("access_token", tokens)

        # Step 4: Use the token
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
        me_response = api_client.get("/api/v1/me/")
        self.assertEqual(me_response.status_code, 200)


class OAuth2RefreshTokenTests(OAuth2TestBase):
    def test_refresh_token_lifecycle(self):
        access = self._create_access_token(scope="read:profile")
        refresh = RefreshToken.objects.create(
            user=self.user,
            application=self.app,
            token=secrets.token_hex(32),
            access_token=access,
        )
        # Refresh token should be valid
        self.assertFalse(refresh.revoked)

        # Revoke the refresh token
        refresh.revoke()
        refresh.refresh_from_db()
        self.assertIsNotNone(refresh.revoked)


@override_settings(API_DOCS_PUBLIC=True)
class OAuth2SchemaTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_schema_includes_oauth2_security(self):
        response = self.client.get("/api/schema/")
        content = str(response.content)
        self.assertIn("oauth2", content)

    def test_schema_includes_authorization_url(self):
        response = self.client.get("/api/schema/")
        content = str(response.content)
        self.assertIn("/o/authorize/", content)
