"""The MCP OAuth hardening, wired and exercised end to end.

``MCP_OAUTH2_PROVIDER_OVERRIDES`` is merged into ``OAUTH2_PROVIDER`` only when
``MCP_ENABLED``. These tests apply that merge explicitly (tests run with MCP off)
and prove:

* the overrides select our validator, the exact-resource audience validator, and
  refresh-token reuse protection;
* a full authorization-code + PKCE flow carrying an RFC 8707 ``resource`` binds
  that resource onto the tokens, a refresh preserves it, and replay of a rotated
  refresh token is refused (RFC 9700 reuse protection).

The CIMD downgrade and the hardened consent screen (which ships with it) are
covered in test_mcp_consent; this covers the resource-binding and
reuse-protection half of the unit with an ordinary public client.
"""

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

from django.conf import settings as dj_settings
from django.test import Client, SimpleTestCase, TestCase, override_settings
from oauth2_provider.models import AccessToken, Application, Grant
from oauth2_provider.settings import oauth2_settings

from speedpycom.api.oauth_validator import SpeedPyOAuth2Validator
from usermodel.models import User

# The provider dict as it is when MCP is enabled, plus an explicit issuer for the
# RFC 9207 `iss` response the overrides turn on.
HARDENED_OAUTH2_PROVIDER = {
    **dj_settings.OAUTH2_PROVIDER,
    **dj_settings.MCP_OAUTH2_PROVIDER_OVERRIDES,
    "OIDC_ISS_ENDPOINT": "https://app.example.com",
}


class OverridesShapeTests(SimpleTestCase):
    def test_overrides_declare_the_expected_hardening(self):
        o = dj_settings.MCP_OAUTH2_PROVIDER_OVERRIDES
        self.assertEqual(
            o["OAUTH2_VALIDATOR_CLASS"],
            "speedpycom.api.oauth_validator.SpeedPyOAuth2Validator",
        )
        self.assertEqual(
            o["RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR"],
            "speedpycom.api.mcp_audience.validate_resource_exact",
        )
        self.assertTrue(o["REFRESH_TOKEN_REUSE_PROTECTION"])
        self.assertIn("none", o["OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED"])
        # CIMD is enabled — it ships together with the hardened consent screen.
        self.assertTrue(o["CIMD_ENABLED"])


@override_settings(MCP_ENABLED=True, OAUTH2_PROVIDER=HARDENED_OAUTH2_PROVIDER)
class WiringTests(SimpleTestCase):
    def test_our_validator_is_selected(self):
        self.assertIs(oauth2_settings.OAUTH2_VALIDATOR_CLASS, SpeedPyOAuth2Validator)

    def test_reuse_protection_and_rotation_on(self):
        self.assertTrue(oauth2_settings.REFRESH_TOKEN_REUSE_PROTECTION)
        self.assertTrue(oauth2_settings.ROTATE_REFRESH_TOKEN)


@override_settings(
    MCP_ENABLED=True,
    OAUTH2_PROVIDER=HARDENED_OAUTH2_PROVIDER,
    SITE_URL="https://app.example.com",
)
class ResourceBindingEndToEndTests(TestCase):
    """A public auth-code client, RFC 8707 resource, refresh, and replay."""

    RESOURCE = "https://mcp.example.com/mcp"
    REDIRECT = "https://client.example.com/callback"

    def setUp(self):
        self.user = User.objects.create_user(
            email="mcp-oauth@example.com", password="mcppass123",
            first_name="Mcp", last_name="Oauth",
        )
        self.app = Application.objects.create(
            name="MCP Connector",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=self.REDIRECT,
        )

    def _pkce(self):
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return verifier, challenge

    def _authorize(self, http, challenge):
        params = {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": self.REDIRECT,
            "scope": "read:profile",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": self.RESOURCE,
        }
        http.get("/o/authorize/", params)
        response = http.post("/o/authorize/", {**params, "allow": "true"})
        self.assertEqual(response.status_code, 302, response.content)
        return parse_qs(urlparse(response["Location"]).query)["code"][0]

    def _exchange(self, http, code, verifier, resource=None):
        body = (
            f"grant_type=authorization_code&code={code}"
            f"&redirect_uri={self.REDIRECT}"
            f"&client_id={self.app.client_id}"
            f"&code_verifier={verifier}"
        )
        if resource is not None:
            body += f"&resource={resource}"
        return http.post("/o/token/", body, content_type="application/x-www-form-urlencoded")

    def test_resource_is_bound_at_authorization_and_inherited_by_issuance(self):
        http = Client()
        http.login(email="mcp-oauth@example.com", password="mcppass123")
        verifier, challenge = self._pkce()
        code = self._authorize(http, challenge)

        # The resource was stored on the authorization grant itself.
        self.assertIn(self.RESOURCE, Grant.objects.get(code=code).resource)

        # Exchange WITHOUT resupplying resource: issuance must INHERIT it from the
        # grant, which is the actual RFC 8707 binding claim.
        token_response = self._exchange(http, code, verifier, resource=None)
        self.assertEqual(token_response.status_code, 200, token_response.content)
        tokens = token_response.json()
        issued = AccessToken.objects.get(token=tokens["access_token"])
        self.assertIn(self.RESOURCE, issued.resource)

        # Refresh WITHOUT resource: rotates and preserves the bound resource.
        first_refresh = tokens["refresh_token"]
        refresh_response = http.post(
            "/o/token/",
            f"grant_type=refresh_token&refresh_token={first_refresh}"
            f"&client_id={self.app.client_id}",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(refresh_response.status_code, 200, refresh_response.content)
        new_tokens = refresh_response.json()
        self.assertNotEqual(new_tokens["refresh_token"], first_refresh)
        self.assertIn(self.RESOURCE, AccessToken.objects.get(token=new_tokens["access_token"]).resource)

        # Replay of the rotated (already-used) refresh token is refused, and reuse
        # protection revokes the family so the new refresh token stops working too.
        replay = http.post(
            "/o/token/",
            f"grant_type=refresh_token&refresh_token={first_refresh}"
            f"&client_id={self.app.client_id}",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(replay.status_code, 400, replay.content)
        after = http.post(
            "/o/token/",
            f"grant_type=refresh_token&refresh_token={new_tokens['refresh_token']}"
            f"&client_id={self.app.client_id}",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(after.status_code, 400, after.content)

    def test_exchange_for_a_resource_the_grant_did_not_authorise_is_refused(self):
        # RFC 8707: a token request may only narrow to a resource the grant
        # authorised. Asking for a foreign resource is invalid_target.
        http = Client()
        http.login(email="mcp-oauth@example.com", password="mcppass123")
        verifier, challenge = self._pkce()
        code = self._authorize(http, challenge)
        response = self._exchange(http, code, verifier, resource="https://mcp.example.com/mcp/t/other")
        self.assertEqual(response.status_code, 400, response.content)
        # DOT returns the OAuth error JSON with a text/html content-type, so parse
        # the body directly rather than via response.json().
        self.assertEqual(json.loads(response.content).get("error"), "invalid_target")
