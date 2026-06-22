from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient


class DynamicClientRegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("dcr-register")

    @override_settings(DCR_ENABLED=True)
    def test_register_device_code_client(self):
        response = self.client.post(
            self.url,
            {
                "client_name": "My CLI Tool",
                "grant_types": ["urn:ietf:params:oauth:grant-type:device_code"],
                "scope": "read:profile read:teams",
                "token_endpoint_auth_method": "none",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("client_id", data)
        self.assertNotIn("client_secret", data)
        self.assertEqual(data["client_name"], "My CLI Tool")
        self.assertEqual(
            data["grant_types"],
            ["urn:ietf:params:oauth:grant-type:device_code"],
        )
        self.assertEqual(data["scope"], "read:profile read:teams")
        self.assertEqual(data["token_endpoint_auth_method"], "none")
        self.assertIn("client_id_issued_at", data)

    @override_settings(DCR_ENABLED=True)
    def test_register_authorization_code_client(self):
        response = self.client.post(
            self.url,
            {
                "client_name": "My Web App",
                "grant_types": ["authorization_code"],
                "scope": "read:profile",
                "token_endpoint_auth_method": "client_secret_basic",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("client_id", data)
        self.assertIn("client_secret", data)
        self.assertEqual(data["client_name"], "My Web App")
        self.assertEqual(data["grant_types"], ["authorization_code"])
        self.assertEqual(data["token_endpoint_auth_method"], "client_secret_basic")

    @override_settings(DCR_ENABLED=False)
    def test_returns_404_when_disabled(self):
        response = self.client.post(
            self.url,
            {"client_name": "Should Fail"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(DCR_ENABLED=True)
    def test_missing_client_name_returns_400(self):
        response = self.client.post(
            self.url,
            {"grant_types": ["authorization_code"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["error"], "invalid_client_metadata")
