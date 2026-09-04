"""Tests for the hosted-MCP host isolation (speedpycom/api/mcp_host.py)."""

from django.core.exceptions import MiddlewareNotUsed
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

from speedpycom.api import mcp_host
from speedpycom.api.mcp_host import MCPHostMiddleware, hostname_of, mcp_hostname

MCP_BASE = "https://mcp.example.com"


class HostnameOfTests(SimpleTestCase):
    def test_bare_host(self):
        self.assertEqual(hostname_of("mcp.example.com"), "mcp.example.com")

    def test_url(self):
        self.assertEqual(hostname_of("https://mcp.example.com/mcp"), "mcp.example.com")

    def test_port_is_ignored(self):
        self.assertEqual(hostname_of("mcp.example.com:443"), "mcp.example.com")

    def test_case_folded(self):
        self.assertEqual(hostname_of("MCP.Example.COM"), "mcp.example.com")

    def test_terminal_dns_dot_is_stripped(self):
        self.assertEqual(hostname_of("mcp.example.com."), "mcp.example.com")
        self.assertEqual(hostname_of("mcp.example.com.:443"), "mcp.example.com")

    def test_empty(self):
        self.assertEqual(hostname_of(""), "")
        self.assertEqual(hostname_of(None), "")


@override_settings(MCP_ENABLED=True, MCP_BASE_URL=MCP_BASE)
class McpHostnameTests(SimpleTestCase):
    def test_reads_base_url(self):
        self.assertEqual(mcp_hostname(), "mcp.example.com")


class MiddlewareEnablementTests(SimpleTestCase):
    @override_settings(MCP_ENABLED=False)
    def test_removes_itself_when_disabled(self):
        with self.assertRaises(MiddlewareNotUsed):
            MCPHostMiddleware(lambda r: r)

    @override_settings(MCP_ENABLED=True, MCP_BASE_URL="")
    def test_noop_when_base_unset(self):
        # Enabled but no base URL: constructs, but isolates nothing.
        mw = MCPHostMiddleware(lambda r: r)
        request = RequestFactory().get("/api/v1/me/")
        self.assertIsNone(mw.process_request(request))


@override_settings(MCP_ENABLED=True, MCP_BASE_URL=MCP_BASE)
class IsolationTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.mw = MCPHostMiddleware(lambda r: r)

    def _request(self, path, host):
        return self.rf.get(path, HTTP_HOST=host)

    # On the MCP host: only the MCP plane answers.
    def test_mcp_transport_allowed_on_mcp_host(self):
        self.assertIsNone(self.mw.process_request(self._request("/mcp", "mcp.example.com")))

    def test_protected_resource_metadata_allowed_on_mcp_host(self):
        req = self._request("/.well-known/oauth-protected-resource", "mcp.example.com")
        self.assertIsNone(self.mw.process_request(req))

    def test_app_paths_404_on_mcp_host(self):
        for path in ("/", "/o/authorize/", "/accounts/login/", "/api/v1/me/", "/static/x.css"):
            with self.assertRaises(Http404):
                self.mw.process_request(self._request(path, "mcp.example.com"))

    def test_sibling_prefix_not_allowed_on_mcp_host(self):
        with self.assertRaises(Http404):
            self.mw.process_request(self._request("/mcpanel", "mcp.example.com"))

    def test_port_on_host_header_does_not_escape(self):
        # Host sent with a port must still be recognised as the MCP host.
        with self.assertRaises(Http404):
            self.mw.process_request(self._request("/", "mcp.example.com:443"))

    def test_trailing_dot_host_does_not_escape(self):
        # mcp.example.com. is the MCP host too — app paths must still 404 there.
        with self.assertRaises(Http404):
            self.mw.process_request(self._request("/", "mcp.example.com."))

    # On the app host: /mcp… is a 404, app paths pass.
    def test_mcp_paths_404_on_app_host(self):
        for path in ("/mcp", "/mcp/t/acme"):
            with self.assertRaises(Http404):
                self.mw.process_request(self._request(path, "app.example.com"))

    def test_app_paths_pass_on_app_host(self):
        self.assertIsNone(self.mw.process_request(self._request("/api/v1/me/", "app.example.com")))


class AllowlistSafetyTests(SimpleTestCase):
    @override_settings(MCP_HOST_ALLOWED_PREFIXES=["/", "", "/mcp"])
    def test_root_and_empty_prefixes_are_dropped(self):
        # A stray "/" must not turn isolation off.
        self.assertEqual(mcp_host._allowed_prefixes(), ("/mcp",))
