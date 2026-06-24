"""Tests for the machine-readable integration manifest."""

import json

from django.test import TestCase, override_settings
from rest_framework.test import APIClient


# Sensitive strings that must never appear in the manifest.
SENSITIVE_PATTERNS = [
    "SECRET",
    "client_secret",
    "signing_secret",
    "ADMIN_URL",
    "password",
]


class IntegrationManifestTestBase(TestCase):
    """Shared helpers for manifest tests."""

    def setUp(self):
        self.client = APIClient()

    def _get_manifest(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        return response.json()


@override_settings(SITE_URL="https://example.test")
class WellKnownManifestTests(IntegrationManifestTestBase):
    """Tests for /.well-known/speedpy.json"""

    URL = "/.well-known/speedpy.json"

    def test_returns_200_unauthenticated(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)

    def test_returns_valid_json(self):
        response = self.client.get(self.URL)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertIsInstance(data, dict)

    def test_manifest_version(self):
        data = self._get_manifest(self.URL)
        self.assertEqual(data["manifest_version"], "1.0")

    def test_service_section(self):
        data = self._get_manifest(self.URL)
        self.assertEqual(data["service"]["name"], "SpeedPy")
        self.assertEqual(data["service"]["base_url"], "https://example.test")

    def test_links_use_site_url(self):
        data = self._get_manifest(self.URL)
        self.assertEqual(data["links"]["openapi_schema"], "https://example.test/api/schema/")
        self.assertEqual(data["links"]["swagger_ui"], "https://example.test/api/docs/")

    def test_auth_methods_present(self):
        data = self._get_manifest(self.URL)
        auth = data["auth"]
        self.assertIn("session", auth)
        self.assertIn("personal_access_token", auth)
        self.assertIn("jwt", auth)
        self.assertIn("oauth2", auth)
        self.assertIn("dynamic_client_registration", auth)

    def test_auth_urls_use_site_url(self):
        data = self._get_manifest(self.URL)
        self.assertEqual(data["auth"]["jwt"]["obtain_url"], "https://example.test/api/auth/token/")
        self.assertEqual(data["auth"]["oauth2"]["authorization_url"], "https://example.test/o/authorize/")

    def test_scopes_present(self):
        data = self._get_manifest(self.URL)
        self.assertIn("read:profile", data["scopes"])
        self.assertIn("write:profile", data["scopes"])
        self.assertIn("read:teams", data["scopes"])

    def test_endpoints_present(self):
        data = self._get_manifest(self.URL)
        self.assertIn("current_user", data["endpoints"])
        self.assertIn("teams", data["endpoints"])
        self.assertIn("webhooks", data["endpoints"])
        self.assertEqual(data["endpoints"]["current_user"]["url"], "https://example.test/api/v1/me/")

    def test_capabilities_present(self):
        data = self._get_manifest(self.URL)
        caps = data["capabilities"]
        self.assertIn("teams_enabled", caps)
        self.assertIn("webhooks_enabled", caps)
        self.assertIn("api_docs_public", caps)
        self.assertIn("webhook_events", caps)
        self.assertIsInstance(caps["webhook_events"], list)
        self.assertGreater(len(caps["webhook_events"]), 0)

    def test_examples_present(self):
        data = self._get_manifest(self.URL)
        self.assertIn("readme", data["examples"])
        self.assertIn("cli", data["examples"])
        self.assertIn("mcp_server", data["examples"])

    def test_no_sensitive_data(self):
        response = self.client.get(self.URL)
        body = response.content.decode()
        for pattern in SENSITIVE_PATTERNS:
            self.assertNotIn(
                pattern.lower(),
                body.lower(),
                f"Manifest should not contain '{pattern}'",
            )


@override_settings(SITE_URL="https://example.test")
class APIManifestTests(IntegrationManifestTestBase):
    """Tests for /api/v1/health/manifest/"""

    URL = "/api/v1/health/manifest/"

    def test_returns_200_unauthenticated(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)

    def test_same_payload_as_well_known(self):
        wk = self._get_manifest("/.well-known/speedpy.json")
        api = self._get_manifest(self.URL)
        self.assertEqual(wk, api)


@override_settings(SITE_URL=None, ALLOWED_HOSTS=["*"])
class ManifestWithoutSiteURLTests(IntegrationManifestTestBase):
    """When SITE_URL is not set, URLs are built from the request host."""

    URL = "/.well-known/speedpy.json"

    def test_urls_built_from_request(self):
        data = self._get_manifest(self.URL)
        # DRF test client uses http://testserver
        self.assertTrue(data["service"]["base_url"].startswith("http"))
        self.assertIn("/api/schema/", data["links"]["openapi_schema"])


@override_settings(SITE_URL="https://example.test", SPEEDPY_TEAMS_ENABLED=False)
class ManifestTeamsDisabledTests(IntegrationManifestTestBase):
    """When teams are disabled, capability is false but endpoints still listed."""

    URL = "/.well-known/speedpy.json"

    def test_teams_disabled_capability(self):
        data = self._get_manifest(self.URL)
        self.assertFalse(data["capabilities"]["teams_enabled"])

    def test_teams_endpoints_still_present_but_disabled(self):
        data = self._get_manifest(self.URL)
        self.assertIn("teams", data["endpoints"])
        self.assertFalse(data["endpoints"]["teams"]["enabled"])


@override_settings(SITE_URL="https://example.test", DCR_ENABLED=False)
class ManifestDCRDisabledTests(IntegrationManifestTestBase):
    """When DCR is disabled, auth entry remains with enabled=false."""

    URL = "/.well-known/speedpy.json"

    def test_dcr_disabled(self):
        data = self._get_manifest(self.URL)
        dcr = data["auth"]["dynamic_client_registration"]
        self.assertFalse(dcr["enabled"])
        self.assertIn("/o/register/", dcr["url"])
