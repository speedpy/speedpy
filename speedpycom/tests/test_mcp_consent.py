"""The hardened OAuth consent screen (speedpycom/api/oauth_consent.py).

Unit-level tests for the labelling seams, and HTTP tests (via a test URLconf that
mounts the view, since the project only mounts it when MCP_ENABLED) for the
CIMD-safe heading, the fail-closed refusal, and a full one-click authorize +
exchange for a downgraded CIMD client.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.conf import settings as dj_settings
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from oauth2_provider.cimd import CIMDError
from oauth2_provider.models import Application, get_application_model

from speedpycom.api.mcp_resource import Resource, ResourceCodec
from speedpycom.api.oauth_consent import ConsentAuthorizationView, _client_host
from usermodel.models import User

MCP_BASE = "https://mcp.example.com"
HARDENED = {
    **dj_settings.OAUTH2_PROVIDER,
    **dj_settings.MCP_OAUTH2_PROVIDER_OVERRIDES,
    "OIDC_ISS_ENDPOINT": "https://app.example.com",
    # DOT caches the oauthlib core (and its validator) as a view-class attribute
    # once built. Another test that exercises /o/ builds it with the stock
    # validator, and override_settings would not rebuild it — so the CIMD
    # downgrade in our validator would never run under test. Forcing a rebuild
    # per request makes the override effective. Production never toggles this at
    # runtime, so it builds the core once with the MCP validator already in place.
    "ALWAYS_RELOAD_OAUTHLIB_CORE": True,
}

CHATGPT_CLIENT_ID = "https://chatgpt.com/oauth/client.json"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CHATGPT_DOC = {
    "client_id": CHATGPT_CLIENT_ID,
    "client_name": "Totally Official Bank",  # self-asserted; must NOT be the heading
    "token_endpoint_auth_method": "private_key_jwt",
    "grant_types": ["authorization_code", "refresh_token"],
    "redirect_uris": [CHATGPT_REDIRECT],
}


class ClientHostTests(SimpleTestCase):
    def test_https_client_id_yields_host(self):
        self.assertEqual(_client_host("https://chatgpt.com/oauth/client.json"), "chatgpt.com")

    def test_ordinary_client_id_yields_empty(self):
        self.assertEqual(_client_host("abc123"), "")
        self.assertEqual(_client_host(None), "")


@override_settings(MCP_BASE_URL=MCP_BASE)
class ResourceLabelTests(SimpleTestCase):
    def _view(self, resources):
        view = ConsentAuthorizationView()
        view._resources = resources
        return view

    def test_single_tenant_default_is_your_account(self):
        self.assertEqual(self._view([f"{MCP_BASE}/mcp"])._resource_label(), "your account")

    def test_no_resource_is_blank(self):
        self.assertEqual(self._view([])._resource_label(), "")

    def test_unknown_resource_reads_as_itself(self):
        # Not one of ours -> shown verbatim, never resolved into a confirmation.
        self.assertEqual(
            self._view(["https://evil.example.com/x"])._resource_label(),
            "https://evil.example.com/x",
        )

    def test_multiple_resources_are_joined(self):
        label = self._view([f"{MCP_BASE}/mcp", f"{MCP_BASE}/other"])._resource_label()
        self.assertIn(",", label)

    def test_describe_resource_is_a_seam(self):
        @dataclass(frozen=True)
        class TeamResource(Resource):
            team_slug: str | None = None

            @property
            def path(self):
                return "mcp" if self.team_slug is None else f"mcp/t/{self.team_slug}"

        class TeamCodec(ResourceCodec):
            resource_class = TeamResource

            def parse_path(self, path):
                if path == "mcp":
                    return TeamResource()
                if path.startswith("mcp/t/") and "/" not in path[len("mcp/t/"):]:
                    return TeamResource(team_slug=path[len("mcp/t/"):])
                return None

        class TeamConsent(ConsentAuthorizationView):
            resource_codec = TeamCodec()

            def describe_resource(self, resource):
                return "every team" if resource.team_slug is None else f"the team {resource.team_slug}"

        view = TeamConsent()
        view._resources = [f"{MCP_BASE}/mcp/t/acme"]
        self.assertEqual(view._resource_label(), "the team acme")


def _pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


class FakeFetcher:
    documents = {CHATGPT_CLIENT_ID: CHATGPT_DOC}
    max_age = 3600

    def fetch(self, client_id):
        try:
            return self.documents[client_id], self.max_age
        except KeyError as exc:
            raise CIMDError(str(client_id)) from exc


def _patch_fetcher():
    from oauth2_provider.settings import oauth2_settings

    _ = oauth2_settings.CIMD_METADATA_FETCHER
    return mock.patch.object(oauth2_settings, "CIMD_METADATA_FETCHER", FakeFetcher)


@override_settings(
    ROOT_URLCONF="speedpycom.tests.urls_mcp",
    MCP_ENABLED=True,
    MCP_BASE_URL=MCP_BASE,
    OAUTH2_PROVIDER=HARDENED,
    MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS=[CHATGPT_CLIENT_ID],
)
class ConsentHttpTests(TestCase):
    def setUp(self):
        # The CIMD failure backoff lives in the process-global cache, which is not
        # rolled back between tests; a leftover key from another test would
        # suppress the downgrade fetch here.
        from django.core.cache import cache

        cache.clear()
        self.user = User.objects.create_user(
            email="consent@example.com", password="consentpass123",
            first_name="Con", last_name="Sent",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _authorize_params(self, **overrides):
        verifier, challenge = _pkce()
        params = {
            "response_type": "code",
            "client_id": CHATGPT_CLIENT_ID,
            "redirect_uri": CHATGPT_REDIRECT,
            "scope": "read:profile",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": f"{MCP_BASE}/mcp",
        }
        params.update(overrides)
        return params, verifier

    def test_cimd_client_is_named_by_host_not_its_claim(self):
        params, _ = self._authorize_params()
        with _patch_fetcher():
            response = self.client.get("/o/authorize/", params)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.content.decode()
        heading = body[body.find("<h2"): body.find("</h2>") + 6]
        # The heading carries the host it cannot forge, never its self-asserted
        # client_name.
        self.assertIn("chatgpt.com", heading)
        self.assertNotIn("Totally Official Bank", heading)

    def test_an_unvalidatable_request_fails_closed_with_400(self):
        # An unknown client cannot be resolved and cannot be bounced to a
        # redirect_uri, so DOT renders the consent template with an error-only
        # context. The hardened view refuses it (400) instead of drawing an
        # Authorize button over blanks.
        params, _ = self._authorize_params(client_id="no-such-client")
        response = self.client.get("/o/authorize/", params)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("refused", response.content.decode().lower())

    def test_a_foreign_resource_is_refused(self):
        params, _ = self._authorize_params(resource="https://evil.example.com/x")
        with _patch_fetcher():
            response = self.client.get("/o/authorize/", params)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("does not recognise", response.content.decode())

    def test_more_than_one_resource_is_refused(self):
        params, _ = self._authorize_params()
        params["resource"] = [f"{MCP_BASE}/mcp", f"{MCP_BASE}/other"]
        with _patch_fetcher():
            response = self.client.get("/o/authorize/", params)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("more than one resource", response.content.decode())

    def test_one_click_authorize_and_exchange_for_a_downgraded_cimd_client(self):
        params, verifier = self._authorize_params()
        with _patch_fetcher():
            # Consent renders, then the user approves.
            self.client.get("/o/authorize/", params)
            approve = self.client.post("/o/authorize/", {**params, "allow": "true"})
            self.assertEqual(approve.status_code, 302, approve.content)
            code = parse_qs(urlparse(approve["Location"]).query)["code"][0]

            # The downgrade persisted a PUBLIC client; exchange with no secret.
            app = get_application_model().objects.get(client_id=CHATGPT_CLIENT_ID)
            self.assertEqual(app.client_type, Application.CLIENT_PUBLIC)

            token = self.client.post(
                "/o/token/",
                f"grant_type=authorization_code&code={code}"
                f"&redirect_uri={CHATGPT_REDIRECT}&client_id={CHATGPT_CLIENT_ID}"
                f"&code_verifier={verifier}&resource={MCP_BASE}/mcp",
                content_type="application/x-www-form-urlencoded",
            )
        self.assertEqual(token.status_code, 200, token.content)
        self.assertIn("access_token", token.json())
