"""Deploy-time checks for hosted-MCP configuration that fails silently.

Django's system checks are the right place for settings whose wrongness does not
raise — it only produces the wrong behaviour, later, somewhere else.
``MCP_BASE_URL`` is exactly that shape: it is the OAuth ``resource`` (RFC 8707)
every hosted MCP URL is built from, so a wrong value does not crash anything. It
mints tokens whose audience does not match the URL clients were told to use, and
the only symptom is that connections mysteriously stop working after consent —
with a valid token, on a live endpoint, for a resource nobody asked for.

Registered by ``speedpycom.apps.SpeedpycomConfig.ready``. Inert unless
``MCP_ENABLED`` is on.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, Warning, register

from speedpycom.api.mcp_host import hostname_of


@register(deploy=True)
def check_mcp_base_url(app_configs, **kwargs):
    """``MCP_BASE_URL`` must be a bare HTTPS origin while MCP is enabled."""
    if not getattr(settings, "MCP_ENABLED", False):
        return []

    base = getattr(settings, "MCP_BASE_URL", "") or ""
    if not base:
        return [
            Error(
                "MCP_ENABLED is on but MCP_BASE_URL is empty.",
                hint=(
                    "Set MCP_BASE_URL to the origin serving the MCP endpoint, "
                    "for example https://mcp.example.com. It is the OAuth "
                    "resource identifier, so it must match the URL users paste "
                    "into their client exactly."
                ),
                id="speedpycom.E001",
            )
        ]

    try:
        parsed = urlsplit(base)
    except ValueError:
        return [
            Error(
                f"MCP_BASE_URL is not a parseable URL: {base!r}.",
                id="speedpycom.E002",
            )
        ]

    errors = []
    if parsed.scheme != "https" and not settings.DEBUG:
        errors.append(
            Error(
                f"MCP_BASE_URL must use https, not {parsed.scheme!r}.",
                hint=(
                    "Both connector directories require the MCP server to be "
                    "reachable over HTTPS, and an OAuth resource identifier over "
                    "http is not a resource either store will accept."
                ),
                id="speedpycom.E003",
            )
        )
    if not parsed.netloc:
        errors.append(
            Error(
                f"MCP_BASE_URL has no host: {base!r}.",
                id="speedpycom.E004",
            )
        )
    if parsed.path.rstrip("/") or parsed.query or parsed.fragment:
        errors.append(
            Error(
                f"MCP_BASE_URL must be a bare origin, with no path, query or "
                f"fragment: {base!r}.",
                hint=(
                    "The path is what distinguishes one MCP resource from "
                    "another (/mcp, /mcp/t/<team>, …). A path in the base would "
                    "appear in every resource identifier and make them all the "
                    "wrong string."
                ),
                id="speedpycom.E005",
            )
        )
    return errors


@register(deploy=True)
def check_site_url_is_not_the_mcp_host(app_configs, **kwargs):
    """``SITE_URL`` must not resolve to the MCP hostname.

    Written from a live incident, not from imagination. ``SITE_URL`` can fall
    back to the first entry of ``ALLOWED_HOSTS``, which the hosting platform
    fills from the attached domains — so attaching ``mcp.example.com`` can
    silently make it the site's own base URL. Nothing fails. The site keeps
    serving. But every absolute URL the app emits — sitemap entries, the OG
    image, invitation and confirmation email links, the OAuth issuer — points at
    a hostname that serves only the MCP plane and 404s everything else.

    The comparison is on **hostnames**, not URL strings: the same host spelled
    with a different scheme or port is still the same host, and must be caught.
    """
    if not getattr(settings, "MCP_ENABLED", False):
        return []

    site_url = getattr(settings, "SITE_URL", "") or ""
    mcp_base = getattr(settings, "MCP_BASE_URL", "") or ""

    if not site_url:
        return [
            Warning(
                "SITE_URL is not set, so absolute URLs are guessed from "
                "ALLOWED_HOSTS.",
                hint=(
                    "Set SITE_URL explicitly. Derived from ALLOWED_HOSTS it "
                    "changes whenever a domain is attached, and it decides every "
                    "link the app emails or publishes."
                ),
                id="speedpycom.W001",
            )
        ]

    site_host = hostname_of(site_url)
    mcp_host = hostname_of(mcp_base)
    if mcp_host and site_host == mcp_host:
        return [
            Error(
                f"SITE_URL and MCP_BASE_URL are the same host: {site_host!r}.",
                hint=(
                    "The MCP hostname serves only the MCP plane; everything else "
                    "404s there. Set SITE_URL to the application's own origin."
                ),
                id="speedpycom.E006",
            )
        ]
    return []
