"""The hosted MCP tool catalogue — the contract and the dispatch.

A :class:`ToolCatalogue` declares what the connector exposes and runs it. It is
the seam a project fills: the base ships **empty** (a working, deny-all connector
with no tools), and a project subclasses it — or just constructs it with its own
:class:`Tool` rows and handlers.

The catalogue is the single source of three facts the transport needs before any
tool runs:

* ``tools/list`` — the schema, title, and annotations of each tool;
* the ``403`` challenge — the exact scope a call needs, named before the call;
* both connector directories — Anthropic rejects a tool without a ``title`` and a
  ``readOnlyHint``/``destructiveHint``, and ChatGPT reads ``securitySchemes`` to
  know a tool needs OAuth.

**One scope per tool.** A tool names the single scope a user is asked to grant
for it, so the ``403`` challenge and the consent screen stay minimal.

**Descriptions describe; they never instruct.** Anthropic rejects a tool whose
description tells the model how to behave or promotes anything. Keep tool text
purely descriptive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

__all__ = ["Tool", "ToolError", "McpContext", "ToolCatalogue"]


class ToolError(Exception):
    """A tool ran but could not do the work — reported to the model as an MCP
    tool error (a ``200`` with ``isError``), not an HTTP failure."""


@dataclass(frozen=True)
class McpContext:
    """What a tool handler is given: the authenticated user, their OAuth access
    token, and the resource the call is bound to."""

    user: Any
    auth: Any  # the OAuth2 AccessToken
    resource: Any  # a speedpycom.api.mcp_resource.Resource


# A handler runs one tool: (context, arguments) -> a JSON-serialisable result.
Handler = Callable[[McpContext, dict], Any]


@dataclass(frozen=True)
class Tool:
    """One tool's contract. ``handler`` executes it; everything else is the
    schema and the permission the transport reads before running it."""

    name: str
    title: str
    description: str
    scope: str
    handler: Handler
    input_schema: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    read_only: bool = True
    destructive: bool = False
    # Argument names fixed by the connector resource (a team/project the URL
    # already names). The framework refuses these from a caller and removes them
    # from the advertised schema; a subclass fills them in ``fill_bound_arguments``.
    bound_arguments: tuple = ()

    def definition(self) -> dict:
        """The ``tools/list`` entry: schema, annotations, and the OAuth scheme.

        ``readOnlyHint``/``destructiveHint`` are required by Anthropic;
        ``securitySchemes`` tells ChatGPT the tool needs OAuth.
        """
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
            },
            "securitySchemes": [{"type": "oauth2", "scopes": [self.scope]}],
        }


class ToolCatalogue:
    """The tools a connector exposes, and how to run one.

    Construct with :class:`Tool` rows, or subclass and override
    :meth:`definitions`, :meth:`bind_arguments`, or :meth:`has_scope` for a
    tenancy-aware connector. The empty default is a safe deny-all: it authenticates
    but offers nothing until tools are installed.
    """

    def __init__(self, tools: Iterable[Tool] = ()):
        self._by_name = {}
        for tool in tools:
            if tool.name in self._by_name:
                raise ValueError(f"Duplicate tool name: {tool.name!r}")
            self._by_name[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._by_name.get(name)

    @property
    def connector_scopes(self) -> list[str]:
        """Every scope the catalogue's tools use — the set advertised in a
        challenge and in the protected-resource metadata."""
        return sorted({tool.scope for tool in self._by_name.values()})

    def definitions(self, resource) -> list[dict]:
        """The ``tools/list`` payload for ``resource``.

        A tool's resource-bound arguments are removed from its advertised schema,
        so an agent on a scoped connector cannot name a different tenant.
        """
        return [self._definition(tool) for tool in self._by_name.values()]

    def _definition(self, tool: Tool) -> dict:
        d = tool.definition()
        if tool.bound_arguments:
            schema = d.get("inputSchema", {}) or {}
            props = {k: v for k, v in schema.get("properties", {}).items() if k not in tool.bound_arguments}
            d = {**d, "inputSchema": {**schema, "properties": props}}
            if "required" in schema:
                d["inputSchema"]["required"] = [r for r in schema["required"] if r not in tool.bound_arguments]
        return d

    def bind_arguments(self, tool: Tool, resource, arguments: dict) -> dict:
        """Return the arguments a handler runs with — framework-owned.

        Refuses any caller-supplied value for a resource-bound argument (a
        confused-deputy defence, enforced here so a fork cannot forget it), then
        fills those arguments from the resource via :meth:`fill_bound_arguments`.
        """
        args = dict(arguments or {})
        for name in tool.bound_arguments:
            if name in args:
                raise ToolError(
                    f"{name} is fixed by the connector URL and cannot be set by the caller."
                )
        args.update(self.fill_bound_arguments(tool, resource))
        return args

    def fill_bound_arguments(self, tool: Tool, resource) -> dict:
        """Values for ``tool``'s resource-bound arguments. The base binds nothing
        (single-tenant). A tenancy-aware subclass resolves the team/project from
        ``resource`` and returns ``{name: value}`` for each of
        ``tool.bound_arguments``."""
        return {}

    def authorize(self, ctx: McpContext, tool: Tool, arguments: dict) -> None:
        """Authorize this call beyond the scope preflight the transport already
        ran: membership, role, billing/entitlement. The base allows (the handler
        remains responsible). Raise :class:`ToolError` to refuse; a subclass may
        raise its own exceptions the transport maps."""

    def has_scope(self, ctx: McpContext, scope: str) -> bool:
        """Whether the context's token carries ``scope``. Uses the OAuth2 access
        token's own scope set. Override to consult a different policy."""
        token = ctx.auth
        return bool(token is not None and token.allow_scopes([scope]))

    def call(self, ctx: McpContext, name: str, arguments: dict | None) -> Any:
        """Run one tool: refuse bound-argument overrides, fill them, authorize,
        then dispatch. Raises :class:`ToolError` for a tool that could not do the
        work; a handler may raise other exceptions the transport maps."""
        if arguments is not None and not isinstance(arguments, dict):
            raise ToolError("arguments must be an object.")
        tool = self.get(name)
        if tool is None:
            raise ToolError(f"There is no tool called {name!r}.")
        bound = self.bind_arguments(tool, ctx.resource, arguments or {})
        self.authorize(ctx, tool, bound)
        return tool.handler(ctx, bound)
