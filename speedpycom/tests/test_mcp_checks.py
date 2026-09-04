"""Tests for the hosted-MCP deploy checks (speedpycom/checks.py)."""

from django.test import SimpleTestCase, override_settings

from speedpycom.checks import check_mcp_base_url, check_site_url_is_not_the_mcp_host


def _ids(results):
    return {r.id for r in results}


class DisabledIsInertTests(SimpleTestCase):
    @override_settings(MCP_ENABLED=False, MCP_BASE_URL="")
    def test_base_url_check_silent_when_disabled(self):
        self.assertEqual(check_mcp_base_url(None), [])

    @override_settings(MCP_ENABLED=False, SITE_URL="https://app.example.com", MCP_BASE_URL="")
    def test_site_url_check_silent_when_disabled(self):
        self.assertEqual(check_site_url_is_not_the_mcp_host(None), [])


@override_settings(MCP_ENABLED=True, DEBUG=False)
class BaseUrlShapeTests(SimpleTestCase):
    @override_settings(MCP_BASE_URL="https://mcp.example.com")
    def test_valid_base_url_passes(self):
        self.assertEqual(check_mcp_base_url(None), [])

    @override_settings(MCP_BASE_URL="")
    def test_missing_base_url_errors(self):
        self.assertEqual(_ids(check_mcp_base_url(None)), {"speedpycom.E001"})

    @override_settings(MCP_BASE_URL="http://mcp.example.com")
    def test_http_errors_in_prod(self):
        self.assertIn("speedpycom.E003", _ids(check_mcp_base_url(None)))

    @override_settings(MCP_BASE_URL="https://mcp.example.com/mcp")
    def test_path_in_base_errors(self):
        self.assertIn("speedpycom.E005", _ids(check_mcp_base_url(None)))

    @override_settings(MCP_BASE_URL="https://mcp.example.com/?x=1")
    def test_query_in_base_errors(self):
        self.assertIn("speedpycom.E005", _ids(check_mcp_base_url(None)))


@override_settings(MCP_ENABLED=True)
class SiteUrlVsMcpHostTests(SimpleTestCase):
    @override_settings(SITE_URL="https://app.example.com", MCP_BASE_URL="https://mcp.example.com")
    def test_distinct_hosts_pass(self):
        self.assertEqual(check_site_url_is_not_the_mcp_host(None), [])

    @override_settings(SITE_URL="", MCP_BASE_URL="https://mcp.example.com")
    def test_unset_site_url_warns(self):
        self.assertEqual(_ids(check_site_url_is_not_the_mcp_host(None)), {"speedpycom.W001"})

    @override_settings(SITE_URL="https://mcp.example.com", MCP_BASE_URL="https://mcp.example.com")
    def test_same_host_errors(self):
        self.assertEqual(_ids(check_site_url_is_not_the_mcp_host(None)), {"speedpycom.E006"})

    @override_settings(
        SITE_URL="http://mcp.example.com:8000",
        MCP_BASE_URL="https://mcp.example.com",
    )
    def test_same_host_different_scheme_and_port_still_caught(self):
        # The string form differs, but the hostname is identical — must be caught.
        self.assertEqual(_ids(check_site_url_is_not_the_mcp_host(None)), {"speedpycom.E006"})

    @override_settings(
        SITE_URL="https://mcp.example.com.",
        MCP_BASE_URL="https://mcp.example.com",
    )
    def test_trailing_dot_spelling_still_caught(self):
        self.assertEqual(_ids(check_site_url_is_not_the_mcp_host(None)), {"speedpycom.E006"})
