"""RFC 8707 audience rules for the hosted MCP endpoint.

The URL an agent is given is the OAuth ``resource``, and the token's audience is
what actually decides. Two rules make that true, and ``django-oauth-toolkit``
supplies neither by default:

**Exact matching, never a prefix.** DOT's default validator matches an audience
as a URL *prefix*, so a token minted for ``https://mcp.example.com/mcp`` would
satisfy ``https://mcp.example.com/mcp/t/acme`` — the exact boundary a scoped
connector exists to hold. :func:`validate_resource_exact` replaces the
comparison with equality, and is wired via
``OAUTH2_PROVIDER["RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR"]`` (only when MCP is
enabled).

**An unbound token is refused, not waved through.** DOT returns ``True`` before
consulting any validator when a token carries no resource at all, and for the
REST API that is correct: every PAT and every legacy token has no audience and
must keep working. On the MCP endpoint it is the opposite — a token with no
audience was never consented to a resource, so it has no boundary to check and
cannot be trusted with one. :func:`token_allows_resource` is the MCP-side rule,
and it fails closed. It also refuses any grant other than authorization code,
because no other grant binds the resource at the moment the user consents.

**No query, no fragment.** RFC 8707 permits a query on a resource indicator, and
DOT's parser *discards* it — which would stop the comparison being exact (an
audience of ``…/mcp?anything`` would then authorise ``…/mcp``). None of the MCP
resources carries a query, so a value bearing one is rejected outright on both
sides.

Pure logic over DOT internals; touches no database and is inert unless wired.
"""

from __future__ import annotations

from oauth2_provider.models import AbstractApplication
from oauth2_provider.oauth2_validators import _parse_and_validate_uri

__all__ = ["validate_resource_exact", "token_allows_resource"]

# Only the authorization-code grant binds a resource at consent time; a device,
# client-credentials, or refresh-minted token never recorded which resource the
# user approved, so it has no audience the MCP endpoint can trust.
_RESOURCE_BINDABLE_GRANTS = frozenset({AbstractApplication.GRANT_AUTHORIZATION_CODE})


def _parse(uri):
    """Parse one URI for comparison, or ``None`` if it cannot be one of ours.

    Wraps DOT's parser with two rules of our own: a query or fragment makes the
    value unusable (the parser drops the query, which would make the match
    inexact), and a parse failure is a refusal rather than an exception.
    """
    if not isinstance(uri, str) or "?" in uri or "#" in uri:
        return None
    try:
        return _parse_and_validate_uri(uri)
    except ValueError:
        return None


def validate_resource_exact(request_uri, audiences):
    """RFC 8707 audience check by equality.

    Signature and role match DOT's ``RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR``
    contract: given the URI being requested and the token's audience list,
    return whether the token may be used here.

    DOT never calls this for a token with an empty audience — that case is
    decided before the validator, and the MCP endpoint handles it through
    :func:`token_allows_resource` instead.
    """
    request_parts = _parse(request_uri)
    if request_parts is None:
        return False
    for audience in audiences or ():
        audience_parts = _parse(audience)
        if audience_parts is not None and audience_parts == request_parts:
            return True
    return False


def token_allows_resource(token, resource_url):
    """Whether an OAuth2 access token may answer for one MCP resource.

    Stricter than the server-wide rule on purpose. A token with no audience is
    refused: it carries no record of which resource the user approved, and the
    hosted MCP has no honest way to guess one. And a token from any grant other
    than authorization code is refused, because no other grant binds the
    resource at the moment the user says yes.
    """
    audiences = getattr(token, "resource", None) or []
    if not audiences:
        return False
    application = getattr(token, "application", None)
    grant = getattr(application, "authorization_grant_type", None)
    if grant not in _RESOURCE_BINDABLE_GRANTS:
        return False
    return validate_resource_exact(resource_url, audiences)
