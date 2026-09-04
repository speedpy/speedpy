"""Tests for the RFC 9728 protected-resource metadata view."""

from django.test import TestCase, override_settings

HOST = "mcp.testserver"
BASE = "https://mcp.testserver"


@override_settings(
    ROOT_URLCONF="speedpycom.tests.urls_mcp_endpoint",
    MCP_ENABLED=True,
    MCP_BASE_URL=BASE,
    SITE_URL="https://app.testserver",
    ALLOWED_HOSTS=["testserver", "mcp.testserver", "app.testserver"],
)
class ProtectedResourceMetadataTests(TestCase):
    URL = "/.well-known/oauth-protected-resource/mcp"

    def test_document_on_the_mcp_host(self):
        r = self.client.get(self.URL, HTTP_HOST=HOST, secure=True)
        self.assertEqual(r.status_code, 200, r.content)
        doc = r.json()
        self.assertEqual(doc["resource"], f"{BASE}/mcp")
        self.assertEqual(doc["authorization_servers"], ["https://app.testserver"])
        # The connector's tool scope, not every registered scope.
        self.assertEqual(doc["scopes_supported"], ["read:profile"])

    def test_bare_form_also_answers(self):
        r = self.client.get("/.well-known/oauth-protected-resource", HTTP_HOST=HOST, secure=True)
        self.assertEqual(r.status_code, 200, r.content)

    def test_404_on_the_wrong_host(self):
        r = self.client.get(self.URL, HTTP_HOST="app.testserver", secure=True)
        self.assertEqual(r.status_code, 404)

    @override_settings(MCP_ENABLED=False)
    def test_404_when_disabled(self):
        r = self.client.get(self.URL, HTTP_HOST=HOST, secure=True)
        self.assertEqual(r.status_code, 404)
