"""
Tests for rate-limit contract: throttle behavior, Retry-After, and
X-RateLimit-* response headers.
"""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from usermodel.models import User

TINY_RATES = {"anon": "2/hour", "user": "3/hour"}
LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def _patch_rates():
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, TINY_RATES)


@override_settings(CACHES=LOCMEM_CACHE)
class AuthenticatedThrottleTests(TestCase):
    """Authenticated requests are throttled at the user rate and include headers."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="throttle@example.com", password="pass123"
        )
        self.client.force_authenticate(user=self.user)

    @_patch_rates()
    def test_requests_within_limit_succeed(self):
        for _ in range(3):
            response = self.client.get("/api/v1/products/")
            self.assertEqual(response.status_code, 200)

    @_patch_rates()
    def test_requests_over_limit_get_429(self):
        for _ in range(3):
            self.client.get("/api/v1/products/")
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 429)

    @_patch_rates()
    def test_429_includes_retry_after(self):
        for _ in range(3):
            self.client.get("/api/v1/products/")
        response = self.client.get("/api/v1/products/")
        self.assertIn("Retry-After", response)

    @_patch_rates()
    def test_rate_limit_headers_present(self):
        response = self.client.get("/api/v1/products/")
        self.assertIn("X-RateLimit-Limit", response)
        self.assertIn("X-RateLimit-Remaining", response)
        self.assertIn("X-RateLimit-Reset", response)

    @_patch_rates()
    def test_rate_limit_limit_matches_configured_rate(self):
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response["X-RateLimit-Limit"], "3")

    @_patch_rates()
    def test_rate_limit_remaining_decrements(self):
        r1 = self.client.get("/api/v1/products/")
        r2 = self.client.get("/api/v1/products/")
        self.assertGreater(
            int(r1["X-RateLimit-Remaining"]), int(r2["X-RateLimit-Remaining"])
        )

    @_patch_rates()
    def test_rate_limit_remaining_is_zero_on_429(self):
        for _ in range(3):
            self.client.get("/api/v1/products/")
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["X-RateLimit-Remaining"], "0")


@override_settings(CACHES=LOCMEM_CACHE, API_DOCS_PUBLIC=True)
class AnonThrottleTests(TestCase):
    """Anonymous requests to public endpoints are throttled at the anon rate."""

    def setUp(self):
        self.client = APIClient()

    @_patch_rates()
    def test_anon_requests_over_limit_get_429(self):
        for _ in range(2):
            self.client.get("/api/schema/")
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 429)

    @_patch_rates()
    def test_anon_429_includes_retry_after(self):
        for _ in range(2):
            self.client.get("/api/schema/")
        response = self.client.get("/api/schema/")
        self.assertIn("Retry-After", response)
