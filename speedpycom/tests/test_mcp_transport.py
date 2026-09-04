"""HTTP tests for the MCP transport (speedpycom/api/mcp.py) via a test URLconf."""

import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application

from usermodel.models import User

HOST = "mcp.testserver"
BASE = "https://mcp.testserver"
RESOURCE_URL = f"{BASE}/mcp"
MODERN = "2026-07-28"


@override_settings(
    ROOT_URLCONF="speedpycom.tests.urls_mcp_endpoint",
    MCP_ENABLED=True,
    MCP_BASE_URL=BASE,
    ALLOWED_HOSTS=["testserver", "mcp.testserver"],
)
class TransportTests(TestCase):
    def _post(self, body, auth=None, **headers):
        if auth:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {auth}"
        # secure=True so request.uri is https, matching MCP_BASE_URL — DOT's
        # verify_request audience-checks a resource-bound token against it.
        return self.client.post(
            "/mcp", json.dumps(body), content_type="application/json",
            HTTP_HOST=HOST, secure=True, **headers,
        )

    def _rpc(self, method, params=None, id=1):
        body = {"jsonrpc": "2.0", "id": id, "method": method}
        if params is not None:
            body["params"] = params
        return body

    def _token(self, *, scope="read:profile", resource=(RESOURCE_URL,), grant=None):
        user = User.objects.create_user(email="t@example.com", password="pw12345678")
        app = Application.objects.create(
            name="c",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=grant or Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://c.example.com/cb",
        )
        return AccessToken.objects.create(
            user=user, application=app, token="testtok123",
            expires=timezone.now() + timedelta(hours=1),
            scope=scope, resource=list(resource),
        ).token

    # -- shape --------------------------------------------------------------

    def test_get_is_405(self):
        r = self.client.get("/mcp", HTTP_HOST=HOST, secure=True)
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r["Allow"], "POST")

    def test_ping(self):
        r = self._post(self._rpc("ping"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["result"], {})

    def test_initialize_negotiates_version_and_names_the_server(self):
        r = self._post(self._rpc("initialize", {"protocolVersion": "2025-06-18"}))
        result = r.json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "test-mcp")

    def test_discover(self):
        r = self._post(self._rpc("server/discover"))
        result = r.json()["result"]
        self.assertIn(MODERN, result["supportedVersions"])
        self.assertEqual(result["instructions"], "A test connector.")

    def test_unknown_method_is_404_modern_and_200_legacy(self):
        modern = self._post(self._rpc("nope", {"_meta": {"io.modelcontextprotocol/protocolVersion": MODERN}}),
                            HTTP_MCP_PROTOCOL_VERSION=MODERN, HTTP_MCP_METHOD="nope")
        self.assertEqual(modern.status_code, 404)
        legacy = self._post(self._rpc("nope"))
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()["error"]["code"], -32601)

    def test_notification_is_202(self):
        r = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(r.status_code, 202)

    def test_bad_json_is_parse_error(self):
        r = self.client.post("/mcp", "{not json", content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(r.json()["error"]["code"], -32700)

    # -- origin / headers ---------------------------------------------------

    def test_foreign_origin_is_refused(self):
        r = self._post(self._rpc("ping"), HTTP_ORIGIN="https://evil.example.com")
        self.assertEqual(r.status_code, 403)

    def test_own_origin_is_allowed(self):
        r = self._post(self._rpc("ping"), HTTP_ORIGIN=BASE)
        self.assertEqual(r.status_code, 200)

    def test_modern_header_mismatch_is_refused(self):
        body = self._rpc("tools/list", {"_meta": {"io.modelcontextprotocol/protocolVersion": MODERN}})
        r = self._post(body, HTTP_MCP_PROTOCOL_VERSION=MODERN, HTTP_MCP_METHOD="tools/call")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], -32020)

    # -- auth ---------------------------------------------------------------

    def test_tools_list_without_a_token_is_401_with_challenge(self):
        r = self._post(self._rpc("tools/list"))
        self.assertEqual(r.status_code, 401)
        self.assertIn("resource_metadata=", r["WWW-Authenticate"])

    def test_unbound_token_is_refused(self):
        r = self._post(self._rpc("tools/list"), auth=self._token(resource=[]))
        self.assertEqual(r.status_code, 401)

    def test_wrong_resource_token_is_refused(self):
        r = self._post(self._rpc("tools/list"), auth=self._token(resource=[f"{BASE}/mcp/t/other"]))
        self.assertEqual(r.status_code, 401)

    def test_non_auth_code_grant_is_refused(self):
        r = self._post(self._rpc("tools/list"), auth=self._token(grant=Application.GRANT_CLIENT_CREDENTIALS))
        self.assertEqual(r.status_code, 401)

    # -- tools --------------------------------------------------------------

    def test_authenticated_tools_list(self):
        r = self._post(self._rpc("tools/list"), auth=self._token())
        tools = r.json()["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["echo"])
        self.assertEqual(tools[0]["annotations"]["readOnlyHint"], True)

    def test_authenticated_tools_call(self):
        body = self._rpc("tools/call", {"name": "echo", "arguments": {"text": "hi"}})
        r = self._post(body, auth=self._token())
        result = r.json()["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"echo": "hi"})

    def test_insufficient_scope_is_403(self):
        body = self._rpc("tools/call", {"name": "echo", "arguments": {}})
        r = self._post(body, auth=self._token(scope=""))
        self.assertEqual(r.status_code, 403)
        self.assertIn("insufficient_scope", r["WWW-Authenticate"])

    def test_unknown_tool_is_invalid_params(self):
        body = self._rpc("tools/call", {"name": "nope"})
        r = self._post(body, auth=self._token())
        self.assertEqual(r.json()["error"]["code"], -32602)

    def test_non_object_arguments_is_invalid_params(self):
        body = self._rpc("tools/call", {"name": "echo", "arguments": ["a", "b"]})
        r = self._post(body, auth=self._token())
        self.assertEqual(r.json()["error"]["code"], -32602)
