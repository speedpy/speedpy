"""Tests for the RFC 8707 audience rules (speedpycom/api/mcp_audience.py)."""

from types import SimpleNamespace

from django.test import SimpleTestCase
from oauth2_provider.models import AbstractApplication

from speedpycom.api.mcp_audience import token_allows_resource, validate_resource_exact

AUTH_CODE = AbstractApplication.GRANT_AUTHORIZATION_CODE
ROOT = "https://mcp.example.com/mcp"
TEAM = "https://mcp.example.com/mcp/t/acme"


class ValidateResourceExactTests(SimpleTestCase):
    def test_equal_audience_matches(self):
        self.assertTrue(validate_resource_exact(ROOT, [ROOT]))

    def test_prefix_does_not_match(self):
        # The whole point: a canonical-URL token must NOT satisfy a team URL.
        self.assertFalse(validate_resource_exact(TEAM, [ROOT]))
        self.assertFalse(validate_resource_exact(ROOT, [TEAM]))

    def test_default_port_is_canonicalised(self):
        # https default port 443 vs explicit :443 parse equal.
        self.assertTrue(validate_resource_exact(ROOT, ["https://mcp.example.com:443/mcp"]))

    def test_one_of_several_audiences_matches(self):
        self.assertTrue(validate_resource_exact(ROOT, [TEAM, ROOT]))

    def test_no_audiences(self):
        self.assertFalse(validate_resource_exact(ROOT, []))
        self.assertFalse(validate_resource_exact(ROOT, None))

    def test_query_or_fragment_is_refused_on_either_side(self):
        self.assertFalse(validate_resource_exact(ROOT + "?x=1", [ROOT]))
        self.assertFalse(validate_resource_exact(ROOT, [ROOT + "?x=1"]))
        self.assertFalse(validate_resource_exact(ROOT + "#x", [ROOT]))

    def test_unparseable_request_uri(self):
        self.assertFalse(validate_resource_exact("://bad", [ROOT]))
        self.assertFalse(validate_resource_exact(None, [ROOT]))


def _token(resource, grant=AUTH_CODE):
    app = SimpleNamespace(authorization_grant_type=grant)
    return SimpleNamespace(resource=resource, application=app)


class TokenAllowsResourceTests(SimpleTestCase):
    def test_bound_auth_code_token_matches(self):
        self.assertTrue(token_allows_resource(_token([ROOT]), ROOT))

    def test_unbound_token_is_refused(self):
        self.assertFalse(token_allows_resource(_token([]), ROOT))
        self.assertFalse(token_allows_resource(_token(None), ROOT))

    def test_non_auth_code_grant_is_refused(self):
        self.assertFalse(
            token_allows_resource(
                _token([ROOT], grant=AbstractApplication.GRANT_CLIENT_CREDENTIALS), ROOT
            )
        )

    def test_wrong_resource_is_refused(self):
        self.assertFalse(token_allows_resource(_token([ROOT]), TEAM))
