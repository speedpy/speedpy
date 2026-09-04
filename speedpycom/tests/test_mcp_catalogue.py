"""Tests for the MCP tool catalogue framework (speedpycom/api/mcp_catalogue.py)."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from speedpycom.api.mcp_catalogue import McpContext, Tool, ToolCatalogue, ToolError


def _tool(name="echo", scope="read:profile", read_only=True, destructive=False, handler=None):
    return Tool(
        name=name,
        title=name.title(),
        description="Return the input.",
        scope=scope,
        handler=handler or (lambda ctx, args: {"echo": args.get("text")}),
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        read_only=read_only,
        destructive=destructive,
    )


def _ctx(scopes="read:profile"):
    token = SimpleNamespace(allow_scopes=lambda wanted: all(s in scopes.split() for s in wanted))
    return McpContext(user=object(), auth=token, resource=object())


class ToolDefinitionTests(SimpleTestCase):
    def test_definition_has_title_hints_and_scheme(self):
        d = _tool(read_only=False, destructive=True).definition()
        self.assertEqual(d["title"], "Echo")
        self.assertEqual(d["annotations"]["readOnlyHint"], False)
        self.assertEqual(d["annotations"]["destructiveHint"], True)
        self.assertEqual(d["securitySchemes"], [{"type": "oauth2", "scopes": ["read:profile"]}])
        self.assertIn("properties", d["inputSchema"])


class EmptyCatalogueTests(SimpleTestCase):
    def test_deny_all_default(self):
        cat = ToolCatalogue()
        self.assertEqual(cat.definitions(resource=None), [])
        self.assertEqual(cat.connector_scopes, [])
        self.assertIsNone(cat.get("anything"))

    def test_calling_a_missing_tool_is_a_tool_error(self):
        with self.assertRaises(ToolError):
            ToolCatalogue().call(_ctx(), "nope", {})


class PopulatedCatalogueTests(SimpleTestCase):
    def setUp(self):
        self.cat = ToolCatalogue([_tool("a", scope="read:profile"), _tool("b", scope="write:profile")])

    def test_get_and_scopes(self):
        self.assertIsNotNone(self.cat.get("a"))
        self.assertEqual(self.cat.connector_scopes, ["read:profile", "write:profile"])

    def test_definitions_lists_every_tool(self):
        names = {d["name"] for d in self.cat.definitions(resource=None)}
        self.assertEqual(names, {"a", "b"})

    def test_duplicate_names_are_rejected(self):
        with self.assertRaises(ValueError):
            ToolCatalogue([_tool("a"), _tool("a")])

    def test_call_dispatches_to_the_handler(self):
        result = self.cat.call(_ctx(), "a", {"text": "hi"})
        self.assertEqual(result, {"echo": "hi"})

    def test_has_scope_reads_the_token(self):
        self.assertTrue(self.cat.has_scope(_ctx("read:profile"), "read:profile"))
        self.assertFalse(self.cat.has_scope(_ctx("read:profile"), "write:profile"))


class BoundArgumentTests(SimpleTestCase):
    """The framework-owned confused-deputy defence: a resource-bound argument is
    refused from the caller, filled from the resource, and hidden from the schema."""

    def _catalogue(self):
        tool = Tool(
            name="list", title="List", description="List items in a team.",
            scope="read:profile", handler=lambda ctx, args: args,
            input_schema={"type": "object", "properties": {"team": {"type": "string"}, "q": {"type": "string"}},
                          "required": ["team"]},
            bound_arguments=("team",),
        )

        class TeamCat(ToolCatalogue):
            def fill_bound_arguments(self, tool, resource):
                return {"team": "acme"}

        return TeamCat([tool])

    def test_caller_cannot_set_a_bound_argument(self):
        with self.assertRaises(ToolError):
            self._catalogue().call(_ctx(), "list", {"team": "other"})

    def test_bound_argument_is_filled_from_the_resource(self):
        result = self._catalogue().call(_ctx(), "list", {"q": "x"})
        self.assertEqual(result, {"q": "x", "team": "acme"})

    def test_bound_argument_is_removed_from_the_advertised_schema(self):
        d = self._catalogue().definitions(resource=None)[0]
        self.assertNotIn("team", d["inputSchema"]["properties"])
        self.assertNotIn("team", d["inputSchema"].get("required", []))
        self.assertIn("q", d["inputSchema"]["properties"])


class AuthorizeHookTests(SimpleTestCase):
    def test_authorize_can_refuse_before_the_handler(self):
        class Gated(ToolCatalogue):
            def authorize(self, ctx, tool, arguments):
                raise ToolError("your role does not allow this")

        cat = Gated([_tool("a", handler=lambda ctx, args: {"ran": True})])
        with self.assertRaises(ToolError):
            cat.call(_ctx(), "a", {})


class NonObjectArgumentsTests(SimpleTestCase):
    def test_a_non_object_arguments_value_is_refused(self):
        cat = ToolCatalogue([_tool("a")])
        with self.assertRaises(ToolError):
            cat.call(_ctx(), "a", ["not", "an", "object"])


class BindArgumentsSeamTests(SimpleTestCase):
    def test_subclass_can_fix_and_refuse_arguments(self):
        class Bound(ToolCatalogue):
            def bind_arguments(self, tool, resource, arguments):
                if "team" in (arguments or {}):
                    raise ToolError("team is fixed by the connector URL")
                return {**(arguments or {}), "team": "acme"}

        cat = Bound([_tool("a", handler=lambda ctx, args: args)])
        self.assertEqual(cat.call(_ctx(), "a", {"text": "x"})["team"], "acme")
        with self.assertRaises(ToolError):
            cat.call(_ctx(), "a", {"team": "other"})
