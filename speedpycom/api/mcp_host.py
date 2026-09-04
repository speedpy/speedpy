"""Host-based separation of the hosted MCP plane.

The MCP endpoint gets its own hostname. On its own, a second hostname separates
nothing: Django serves **one** URL conf on **every** host in ``ALLOWED_HOSTS``,
so attaching ``mcp.example.com`` to the same application would publish the whole
product on it — ``/o/``, ``/api/``, ``/accounts/``, the dashboard, the sign-up
form. That is worse than no second host at all: a directory reviewer sees one
origin doing everything, the login form becomes reachable on an origin agents
were told to point tools at, and the cookie-free promise the MCP plane makes is
only a promise.

This middleware is the separation, and it cuts both ways:

* on the MCP host, only the MCP plane answers — the transport, the RFC 9728
  document, any store domain-verification file, and health. Everything else is a
  404, as if the app were not there;
* on every other host, ``/mcp…`` is a 404 — because the URL *is* the OAuth
  resource identifier, and the same endpoint answering on a second origin would
  mean one endpoint with two audiences, which is exactly the boundary the design
  exists to hold.

**Inert until adopted.** The middleware removes itself (``MiddlewareNotUsed``)
unless ``MCP_ENABLED`` is on, and does nothing while ``MCP_BASE_URL`` is unset,
so a deployment that has not adopted the hosted MCP endpoint is unaffected.

The allowlist is settings-driven (``MCP_HOST_ALLOWED_PREFIXES``) and
deny-by-default: an empty or ``"/"`` prefix is dropped so a misconfiguration can
never re-expose the whole app on the MCP host.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import Http404
from django.utils.deprecation import MiddlewareMixin

__all__ = ["MCPHostMiddleware", "hostname_of", "mcp_hostname"]

# Fallback allowlist when MCP_HOST_ALLOWED_PREFIXES is unset. A project adds its
# own store domain-verification paths (e.g. "/.well-known/openai-apps-challenge")
# via that setting rather than editing this list.
_DEFAULT_ALLOWED_PREFIXES = (
    "/mcp",
    "/.well-known/oauth-protected-resource",
    "/health/",
)


def hostname_of(value):
    """The lowercased hostname of a URL or a bare ``Host`` header, or ``""``.

    Parsed, never compared as a string. ``request.get_host()`` returns the
    ``Host`` header as sent — port and all — while a configured base URL usually
    carries none, so a raw string comparison lets ``Host: mcp.example.com:443``
    read as a *different* host and walk straight past the isolation. Parsing also
    handles case and bracketed IPv6 literals, and refuses a malformed authority
    rather than raising on it.

    The port is deliberately not part of the comparison. What separates the two
    planes is the name; one deployment reached on two ports is still one
    deployment. Scheme and port are checked where they matter — in the audience
    comparison, which decides what a token may reach.
    """
    if not value:
        return ""
    try:
        hostname = urlsplit(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return ""
    hostname = (hostname or "").lower()
    # A fully-qualified name may carry a terminal root dot. Django normalises it
    # away when it validates the Host header against ALLOWED_HOSTS, so
    # ``mcp.example.com.`` reaches the app as the MCP host — the comparison here
    # must strip it too, or that spelling walks past the isolation.
    if hostname.endswith("."):
        hostname = hostname[:-1]
    return hostname


def mcp_hostname():
    """Hostname of ``MCP_BASE_URL``, or ``""`` when it is unset."""
    return hostname_of((getattr(settings, "MCP_BASE_URL", "") or "").strip())


def _allowed_prefixes():
    """The configured MCP-host allowlist, with empty and ``"/"`` entries dropped.

    Dropping them is a safety net: a stray ``"/"`` in the setting would match
    every path and turn the isolation off. Prefixes are normalized to a bare
    form (no trailing slash) for the sibling-safe comparison below.
    """
    raw = getattr(settings, "MCP_HOST_ALLOWED_PREFIXES", None) or _DEFAULT_ALLOWED_PREFIXES
    prefixes = []
    for prefix in raw:
        base = (prefix or "").rstrip("/")
        if base:  # drops "" and "/"
            prefixes.append(base)
    return tuple(prefixes)


def _is_allowed_on_mcp_host(path):
    """Whether ``path`` is part of the MCP plane.

    A prefix matches the path itself or anything below it, and never a longer
    sibling: ``/mcp`` allows ``/mcp`` and ``/mcp/t/acme``, but not ``/mcpanel``.
    """
    for base in _allowed_prefixes():
        if path == base or path.startswith(base + "/"):
            return True
    return False


class MCPHostMiddleware(MiddlewareMixin):
    """Serve the MCP plane on the MCP host, and nothing else anywhere.

    Placed **above** WhiteNoise in ``MIDDLEWARE`` so a static file on the MCP
    host is refused too.
    """

    def __init__(self, get_response=None):
        if not getattr(settings, "MCP_ENABLED", False):
            raise MiddlewareNotUsed()
        super().__init__(get_response)

    def process_request(self, request):
        expected = mcp_hostname()
        if not expected:
            return None

        # request.get_host() returns the Host header as sent, including any port;
        # the comparison is on the parsed hostname, never the string.
        host = hostname_of(request.get_host())
        path = request.path

        if host == expected:
            if not _is_allowed_on_mcp_host(path):
                raise Http404("Not served on this host.")
            return None

        # A different host. The MCP paths belong to the MCP origin alone: the URL
        # is the audience, and one endpoint must not have two of them.
        if path == "/mcp" or path.startswith("/mcp/"):
            raise Http404("The MCP endpoint is served on its own host.")
        return None
