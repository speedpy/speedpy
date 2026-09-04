"""Hosted-MCP resource identifiers — the OAuth ``resource`` (RFC 8707).

A :class:`ResourceCodec` parses, builds, and canonicalizes the resource
identifier of a hosted MCP endpoint. The **URL is the resource; the token's
audience is the boundary** — this module only reads and writes the identifier,
it never grants anything and never touches the database.

The base owns the security-critical parts, so a project's tenancy grammar cannot
weaken the audience boundary:

* the origin must equal ``MCP_BASE_URL`` **exactly** — scheme, host, and port —
  so a token minted for someone else's ``resource`` can never satisfy ours;
* a control character, a query, or a fragment makes the value unusable, because
  ``urlsplit`` silently strips some of them and RFC 8707 permits a query, either
  of which would stop the later audience comparison being exact;
* a trailing slash is normalized away — the MCP spec says a canonical resource
  URI SHOULD omit it, and two spellings would mean two audiences for one
  endpoint.

Only the **path grammar** is a project seam. The base is single-tenant: the one
resource is the bare ``/mcp`` root and the token's user is the tenant. Subclass
:meth:`ResourceCodec.parse_path` (and define your own :class:`Resource`) to add
team- or project-scoped shapes. See
``agents_docs/working_with_hosted_mcp.md``.

Inert until a project sets ``MCP_BASE_URL``; nothing here runs at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

__all__ = ["MCP_PATH_PREFIX", "Resource", "ResourceCodec", "base_url"]

MCP_PATH_PREFIX = "mcp"


@dataclass(frozen=True)
class Resource:
    """A parsed MCP resource, before any membership or role check.

    The single-tenant base carries no fields: the one resource is the endpoint
    root. A subclass adds its tenancy fields and overrides :attr:`path`.
    """

    @property
    def path(self) -> str:
        """Path component, without a leading or trailing slash."""
        return MCP_PATH_PREFIX


def base_url() -> str:
    """Origin of the hosted MCP endpoint, without a trailing slash."""
    return (getattr(settings, "MCP_BASE_URL", "") or "").rstrip("/")


class ResourceCodec:
    """Parse / build / canonicalize MCP resource identifiers. No database access.

    Override :meth:`parse_path` (and set :attr:`resource_class`) to supply a
    tenancy grammar; leave everything else alone — it is the audience boundary.
    """

    path_prefix: str = MCP_PATH_PREFIX
    resource_class: type[Resource] = Resource

    # -- the one override point: the path grammar --------------------------

    def parse_path(self, path: str) -> Resource | None:
        """Parse the slash-free path half of a resource, or ``None``.

        ``path`` arrives already stripped of a single leading and trailing
        slash. The base accepts only the bare prefix (``"mcp"``); override to
        recognise scoped shapes such as ``"mcp/t/<team>"``.
        """
        return self.resource_class() if path == self.path_prefix else None

    # -- generic, security-critical: do not override -----------------------

    def base_url(self) -> str:
        return base_url()

    def build_url(self, resource: Resource) -> str:
        """The canonical resource identifier for ``resource``.

        The built URL is required to **round-trip**: parsing it back must yield
        an equal resource. This is the build-side half of the audience boundary —
        a subclass whose ``path`` smuggled a ``/``, ``?``, ``#``, control
        character, or a non-canonical trailing slash (e.g. from an unvalidated
        slug) would produce a *different* audience string, and that is refused
        here rather than minted. Requires ``MCP_BASE_URL`` to be set.
        """
        url = f"{self.base_url()}/{resource.path}"
        if self.parse_url(url) != resource:
            raise ValueError(
                f"Resource does not round-trip through the codec: "
                f"{resource!r} -> {url!r}. Check the slug/grammar for a slash, "
                f"query, fragment, or control character."
            )
        return url

    def parse_url(self, url: str | None) -> Resource | None:
        """Parse a full resource URL, or ``None`` if it is not one of ours."""
        if not url:
            return None
        # urlsplit silently strips ASCII tabs and newlines (the WHATWG rule), so
        # a URL carrying them would parse equal to the canonical one while being
        # a different string. An audience comparison cannot afford that.
        if any(ch < " " or ch == "\x7f" for ch in url):
            return None
        base = self.base_url()
        if not base:
            return None
        # A malformed authority (a broken IPv6 literal, an NFKC-invalid host)
        # makes urlsplit raise. The value is attacker-controlled — it must come
        # back "not ours", never a 500.
        try:
            parsed, expected = urlsplit(url), urlsplit(base)
        except ValueError:
            return None
        if parsed.scheme.lower() != expected.scheme.lower():
            return None
        if parsed.netloc.lower() != expected.netloc.lower():
            return None
        # Bare delimiters parse to empty strings, so testing truthiness would let
        # "…/mcp?" and "…/mcp#" through as if they were the clean form.
        if "?" in url or "#" in url:
            return None
        prefix = expected.path.rstrip("/")
        path = parsed.path
        if prefix:
            if not path.startswith(prefix + "/"):
                return None
            path = path[len(prefix):]
        return self.parse_path_normalized(path)

    def parse_path_normalized(self, path: str | None) -> Resource | None:
        """Strip one optional leading and trailing slash, then :meth:`parse_path`.

        ``//mcp//`` is not a spelling of this resource — exactly one leading and
        one trailing slash are removed, not any number of them.
        """
        if not path:
            return None
        if path.startswith("/"):
            path = path[1:]
        if path.endswith("/"):
            path = path[:-1]
        if not path:
            return None
        return self.parse_path(path)
