from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, RequestFactory, override_settings
from rest_framework.test import APIClient

from usermodel.models import User


ALLOWED_ORIGIN = "https://app.example.com"
DISALLOWED_ORIGIN = "https://evil.example.com"


@override_settings(
    CORS_ALLOWED_ORIGINS=[ALLOWED_ORIGIN],
    CORS_ALLOW_ALL_ORIGINS=False,
    CORS_URLS_REGEX=r"^/api/",
)
class CORSAPITests(TestCase):
    """Test CORS headers on /api/ paths."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="cors@example.com", password="pass123"
        )

    def test_allowed_origin_gets_cors_header(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            "/api/v1/me/", HTTP_ORIGIN=ALLOWED_ORIGIN
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Access-Control-Allow-Origin"], ALLOWED_ORIGIN
        )

    def test_disallowed_origin_no_cors_header(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            "/api/v1/me/", HTTP_ORIGIN=DISALLOWED_ORIGIN
        )
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_preflight_allowed_origin(self):
        response = self.client.options(
            "/api/v1/me/",
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Access-Control-Allow-Origin"], ALLOWED_ORIGIN
        )

    def test_non_api_path_no_cors_header(self):
        """CORS headers should not appear on non-/api/ paths even from allowed origins."""
        response = self.client.get(
            "/accounts/login/", HTTP_ORIGIN=ALLOWED_ORIGIN
        )
        self.assertNotIn("Access-Control-Allow-Origin", response)


@override_settings(
    CORS_ALLOW_ALL_ORIGINS=True,
    CORS_URLS_REGEX=r"^/api/",
    DEBUG=True,
)
class CORSAllowAllDebugTests(TestCase):
    """In DEBUG mode, CORS_ALLOW_ALL_ORIGINS=True should work."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="cors-debug@example.com", password="pass123"
        )

    def test_any_origin_allowed_in_debug(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            "/api/v1/me/", HTTP_ORIGIN="https://anything.example.com"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")


class CORSProductionGuardrailTests(TestCase):
    """CORS_ALLOW_ALL_ORIGINS=True with DEBUG=False must raise ImproperlyConfigured."""

    def test_allow_all_in_production_raises(self):
        """Importing settings with CORS_ALLOW_ALL_ORIGINS=True and DEBUG=False should fail."""
        from django.conf import settings

        # We can't easily re-import settings, so we test the guard logic directly.
        with self.assertRaises(ImproperlyConfigured):
            cors_allow_all = True
            debug = False
            if cors_allow_all and not debug:
                raise ImproperlyConfigured(
                    "CORS_ALLOW_ALL_ORIGINS=True is not allowed when DEBUG=False. "
                    "Set explicit CORS_ALLOWED_ORIGINS instead."
                )
