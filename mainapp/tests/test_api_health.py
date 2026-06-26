"""Tests for the integration health-check endpoint."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient


SENSITIVE_PATTERNS = [
    "SECRET",
    "client_secret",
    "signing_secret",
    "ADMIN_URL",
    "password",
    "DATABASE",
    "INSTALLED_APPS",
]


class HealthCheckTestBase(TestCase):
    """Shared helpers for health-check tests."""

    def setUp(self):
        self.client = APIClient()

    def _get_health(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        return response.json()


@override_settings(SITE_URL="https://example.test")
class APIHealthCheckTests(HealthCheckTestBase):
    """Tests for GET /api/v1/health/"""

    URL = "/api/v1/health/"

    def test_returns_200_unauthenticated(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)

    def test_returns_valid_json(self):
        response = self.client.get(self.URL)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertIsInstance(data, dict)

    def test_status_ok(self):
        data = self._get_health(self.URL)
        self.assertEqual(data["status"], "ok")

    def test_api_version_present(self):
        data = self._get_health(self.URL)
        self.assertEqual(data["api_version"], "1.0.0")

    def test_schema_version_present(self):
        data = self._get_health(self.URL)
        self.assertEqual(data["schema_version"], "1.0")

    def test_timestamp_present(self):
        data = self._get_health(self.URL)
        self.assertIn("timestamp", data)
        self.assertIsInstance(data["timestamp"], str)
        self.assertGreater(len(data["timestamp"]), 0)

    def test_features_teams_enabled(self):
        data = self._get_health(self.URL)
        self.assertIn("features", data)
        self.assertIn("teams_enabled", data["features"])
        self.assertTrue(data["features"]["teams_enabled"])

    def test_no_sensitive_data(self):
        response = self.client.get(self.URL)
        body = response.content.decode()
        for pattern in SENSITIVE_PATTERNS:
            self.assertNotIn(
                pattern.lower(),
                body.lower(),
                f"Health response should not contain '{pattern}'",
            )


@override_settings(
    SITE_URL="https://example.test", SPEEDPY_TEAMS_ENABLED=False
)
class HealthCheckTeamsDisabledTests(HealthCheckTestBase):
    """teams_enabled reflects the SPEEDPY_TEAMS_ENABLED setting."""

    URL = "/api/v1/health/"

    def test_teams_disabled(self):
        data = self._get_health(self.URL)
        self.assertFalse(data["features"]["teams_enabled"])


@override_settings(SITE_URL="https://example.test")
class RootHealthCheckTests(HealthCheckTestBase):
    """Tests for GET /health/"""

    URL = "/health/"

    def test_returns_200_unauthenticated(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)

    def test_same_payload_as_api_health(self):
        root = self._get_health(self.URL)
        api = self._get_health("/api/v1/health/")
        # Timestamps may differ slightly; compare everything else.
        root.pop("timestamp")
        api.pop("timestamp")
        self.assertEqual(root, api)


@override_settings(SITE_URL="https://example.test", API_DOCS_PUBLIC=True)
class HealthCheckSchemaTests(HealthCheckTestBase):
    """Health endpoint appears in the OpenAPI schema."""

    def test_health_in_openapi_schema(self):
        response = self.client.get("/api/schema/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertIn("/api/v1/health/", schema.get("paths", {}))
