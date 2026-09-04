"""RFC 9728 protected-resource metadata for the hosted MCP endpoint.

``django-oauth-toolkit`` builds this document from the live configuration, so it
cannot drift from what ``/o/`` actually does. What it cannot know is **which
resources are real**: its own route answers for any path at all, which would
advertise ``…/mcp/t/whatever`` and send a client through an OAuth flow ending at
a URL that was never a resource. So this view narrows the document to the shapes
the connector actually serves, and its URL patterns are explicit rather than
DOT's ``<path:resource_path>`` catch-all.

**It does not check that the team/project exists.** Checking would turn an
unauthenticated endpoint into an enumeration oracle. A client that authorises
against a resource nobody owns simply fails at the first tool call.

**It is host-bound.** RFC 9728 derives this URL from the resource identifier, so
the same document served from the app's origin would describe a resource that is
somewhere else. On the wrong host it 404s.

**Seams.** Set :attr:`catalogue` and :attr:`resource_codec` to your connector's.
Build URL patterns for your resource shapes with
:func:`mcp_metadata_urlpatterns` (the single-tenant default) or by adding your own
``path()`` entries pointing at ``MCPProtectedResourceMetadataView.as_view()``.
"""

from __future__ import annotations

from django.conf import settings
from django.http import Http404
from django.urls import path
from oauth2_provider.views import OAuthProtectedResourceMetadataView

from speedpycom.api.mcp_catalogue import ToolCatalogue
from speedpycom.api.mcp_host import hostname_of, mcp_hostname
from speedpycom.api.mcp_resource import ResourceCodec, base_url as mcp_base_url

__all__ = ["MCPProtectedResourceMetadataView", "mcp_metadata_urlpatterns"]


class MCPProtectedResourceMetadataView(OAuthProtectedResourceMetadataView):
    """RFC 9728 metadata for one hosted MCP resource."""

    catalogue: ToolCatalogue = ToolCatalogue()
    resource_codec: ResourceCodec = ResourceCodec()

    def _resource(self, request, kwargs):
        """The resource this request is about, or 404.

        Built from ``MCP_BASE_URL`` and the URL's own captured slugs, so the
        advertised ``resource`` is always the canonical spelling a token will be
        bound to — never whatever spelling the caller typed.
        """
        if not getattr(settings, "MCP_ENABLED", False):
            raise Http404("The hosted MCP endpoint is not enabled.")
        if not mcp_base_url():
            raise Http404("No MCP base URL is configured.")
        # Compare parsed hostnames, not strings.
        if hostname_of(request.get_host()) != mcp_hostname():
            raise Http404("Not served on this host.")
        return self.resource_codec.resource_class(**kwargs)

    def get(self, request, *args, **kwargs):
        # Resolve (and refuse) before DOT builds anything.
        self._mcp_resource = self._resource(request, kwargs)
        return super().get(request, *args, **kwargs)

    def get_resource(self, request):
        return self.resource_codec.build_url(self._mcp_resource)

    def get_authorization_servers(self, request):
        # Our own issuer, and only ours. Clients use the first entry.
        return [(settings.SITE_URL or "").rstrip("/")]

    def get_scopes_supported(self):
        # The connector's tool scopes, not every registered scope — a client
        # reads this and asks for all of them at consent.
        return list(self.catalogue.connector_scopes)

    def get_resource_name(self):
        return getattr(settings, "TITLE", "")

    def get_resource_documentation(self):
        return f"{(settings.SITE_URL or '').rstrip('/')}/api/docs/"


def mcp_metadata_urlpatterns(view=None):
    """URL patterns for the single-tenant protected-resource document.

    Returns the bare ``.well-known/oauth-protected-resource`` (which clients probe
    first) and the ``…/mcp`` form. A tenancy-aware connector adds its own scoped
    patterns pointing at the same view. Pass a customised ``view`` (e.g. a
    subclass with your catalogue) or omit it for the default.
    """
    view = view or MCPProtectedResourceMetadataView.as_view()
    return [
        path(".well-known/oauth-protected-resource", view, name="mcp_resource_metadata"),
        path(".well-known/oauth-protected-resource/mcp", view, name="mcp_resource_metadata_canonical"),
    ]
