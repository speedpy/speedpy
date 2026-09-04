"""A test URLconf mounting the MCP transport + RFC 9728 metadata with a small
catalogue, so transport/metadata HTTP tests can exercise the real views (the
project only mounts them when MCP_ENABLED at import)."""

from django.urls import path

from speedpycom.api.mcp import MCPEndpointView
from speedpycom.api.mcp_catalogue import Tool, ToolCatalogue
from speedpycom.api.mcp_metadata import MCPProtectedResourceMetadataView, mcp_metadata_urlpatterns


def _echo(ctx, args):
    return {"echo": args.get("text", "")}


CATALOGUE = ToolCatalogue(
    [
        Tool(
            name="echo",
            title="Echo",
            description="Return the input text.",
            scope="read:profile",
            handler=_echo,
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        ),
    ]
)


class TestEndpoint(MCPEndpointView):
    server_name = "test-mcp"
    instructions = "A test connector."
    catalogue = CATALOGUE


class TestMetadata(MCPProtectedResourceMetadataView):
    catalogue = CATALOGUE


urlpatterns = [
    *mcp_metadata_urlpatterns(TestMetadata.as_view()),
    path("mcp", TestEndpoint.as_view(), name="mcp_endpoint"),
]
