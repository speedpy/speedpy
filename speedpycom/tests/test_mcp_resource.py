"""Tests for the hosted-MCP ResourceCodec base (speedpycom/api/mcp_resource.py)."""

from dataclasses import dataclass

from django.test import SimpleTestCase, override_settings

from speedpycom.api.mcp_resource import MCP_PATH_PREFIX, Resource, ResourceCodec

BASE = "https://mcp.example.com"


@override_settings(MCP_BASE_URL=BASE)
class ResourceCodecTests(SimpleTestCase):
    def setUp(self):
        self.codec = ResourceCodec()

    def test_build_url_of_root(self):
        self.assertEqual(self.codec.build_url(Resource()), f"{BASE}/mcp")

    def test_parse_canonical_url(self):
        self.assertIsInstance(self.codec.parse_url(f"{BASE}/mcp"), Resource)

    def test_trailing_slash_is_normalised(self):
        self.assertIsInstance(self.codec.parse_url(f"{BASE}/mcp/"), Resource)

    def test_wrong_origin_is_refused(self):
        self.assertIsNone(self.codec.parse_url("https://evil.example.com/mcp"))

    def test_scheme_must_match(self):
        self.assertIsNone(self.codec.parse_url("http://mcp.example.com/mcp"))

    def test_query_and_fragment_are_refused(self):
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp?x=1"))
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp#x"))
        # Bare delimiters must not slip through as the clean form.
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp?"))
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp#"))

    def test_control_characters_are_refused(self):
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp\n"))
        self.assertIsNone(self.codec.parse_url(f"{BASE}/m\tcp"))

    def test_unknown_path_is_not_ours(self):
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcpanel"))
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp/t/acme"))

    def test_malformed_authority_returns_none_not_500(self):
        self.assertIsNone(self.codec.parse_url("https://[bad::/mcp"))

    def test_empty_and_none(self):
        self.assertIsNone(self.codec.parse_url(None))
        self.assertIsNone(self.codec.parse_url(""))

    def test_prefix_constant(self):
        self.assertEqual(MCP_PATH_PREFIX, "mcp")


@override_settings(MCP_BASE_URL="")
class UnsetBaseUrlTests(SimpleTestCase):
    def test_parse_url_none_when_base_unset(self):
        self.assertIsNone(ResourceCodec().parse_url("https://mcp.example.com/mcp"))


# A minimal team grammar to prove the base is a real seam, not team/project-bound.
@dataclass(frozen=True)
class TeamResource(Resource):
    team_slug: str | None = None

    @property
    def path(self) -> str:
        if self.team_slug is None:
            return "mcp"
        return f"mcp/t/{self.team_slug}"


class TeamCodec(ResourceCodec):
    resource_class = TeamResource

    def parse_path(self, path):
        if path == self.path_prefix:
            return TeamResource()
        if path.startswith("mcp/t/"):
            slug = path[len("mcp/t/"):]
            if slug and "/" not in slug:
                return TeamResource(team_slug=slug)
        return None


@override_settings(MCP_BASE_URL=BASE)
class SubclassGrammarTests(SimpleTestCase):
    def setUp(self):
        self.codec = TeamCodec()

    def test_root_still_parses(self):
        self.assertEqual(self.codec.parse_url(f"{BASE}/mcp"), TeamResource())

    def test_team_scope_parses(self):
        self.assertEqual(
            self.codec.parse_url(f"{BASE}/mcp/t/acme"),
            TeamResource(team_slug="acme"),
        )

    def test_team_build_roundtrip(self):
        res = TeamResource(team_slug="acme")
        self.assertEqual(self.codec.build_url(res), f"{BASE}/mcp/t/acme")
        self.assertEqual(self.codec.parse_url(self.codec.build_url(res)), res)

    def test_deeper_shape_not_recognised_by_this_grammar(self):
        self.assertIsNone(self.codec.parse_url(f"{BASE}/mcp/t/acme/p/widgets"))

    def test_build_refuses_a_slug_that_would_change_the_audience(self):
        # A slug smuggling a slash, query, or control char would build a
        # different audience string; build_url must refuse to mint it.
        for bad in ("a/b", "a?b", "a#b", "a\tb"):
            with self.assertRaises(ValueError):
                self.codec.build_url(TeamResource(team_slug=bad))
