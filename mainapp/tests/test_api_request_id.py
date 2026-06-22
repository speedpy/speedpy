"""
Tests for the X-Request-ID correlation header contract.
"""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from usermodel.models import User


class RequestIDTests(TestCase):
    """X-Request-ID is echoed on all API responses."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="reqid@example.com", password="pass123"
        )
        self.client.force_authenticate(user=self.user)

    def test_generated_request_id_on_success(self):
        """A request without X-Request-ID gets a generated one in the response."""
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response)
        # Should be a valid UUID
        uuid.UUID(response["X-Request-ID"])

    def test_client_supplied_request_id_echoed(self):
        """A valid client-supplied X-Request-ID is echoed back."""
        client_id = str(uuid.uuid4())
        response = self.client.get(
            "/api/v1/products/", HTTP_X_REQUEST_ID=client_id
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-ID"], client_id)

    def test_invalid_request_id_replaced(self):
        """An invalid X-Request-ID is silently replaced with a generated UUID."""
        response = self.client.get(
            "/api/v1/products/",
            HTTP_X_REQUEST_ID="invalid id with spaces and $pecial chars!!!",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response)
        returned = response["X-Request-ID"]
        self.assertNotEqual(returned, "invalid id with spaces and $pecial chars!!!")
        uuid.UUID(returned)  # Should be a valid UUID

    def test_oversized_request_id_replaced(self):
        """A too-long X-Request-ID is replaced."""
        long_id = "a" * 200
        response = self.client.get(
            "/api/v1/products/", HTTP_X_REQUEST_ID=long_id
        )
        self.assertIn("X-Request-ID", response)
        self.assertNotEqual(response["X-Request-ID"], long_id)

    def test_error_response_includes_request_id(self):
        """Error responses also include X-Request-ID."""
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v1/products/")
        self.assertIn(response.status_code, [401, 403])
        self.assertIn("X-Request-ID", response)

    def test_request_id_on_404(self):
        """404 responses include X-Request-ID."""
        response = self.client.get(f"/api/v1/teams/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("X-Request-ID", response)
