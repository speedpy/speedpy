"""The hosted remote MCP transport — one POST endpoint, both protocol eras.

Revision ``2026-07-28`` removed the GET stream, the session id, and the
``initialize`` handshake, so a conformant server is POST-only and may always
answer with a single JSON object. This view speaks that shape and, for the store
clients that still send it, the older ``initialize`` handshake — same tools, same
permissions, same results, different framing.

**The refusal shapes are the load-bearing part.** An unauthenticated or
wrong-audience call fails the *HTTP request* with ``401`` + ``WWW-Authenticate``
naming where the resource metadata lives, so the client runs the sign-in flow. A
``200`` carrying ``isError`` produces no sign-in prompt — the model just reads the
error and moves on — so it is used only for a tool that genuinely could not do
the work. Insufficient scope is a ``403`` naming the exact scope. Both happen
*before* the tool runs.

**What may call it.** Authorization-code OAuth tokens bound to this exact
resource (RFC 8707), and nothing else — no cookies, no session, no PAT. The
endpoint is credential-free by construction, so it has no CSRF or CORS surface.

**Seams.** Set :attr:`catalogue` (a :class:`~speedpycom.api.mcp_catalogue.ToolCatalogue`)
and :attr:`resource_codec` (a :class:`~speedpycom.api.mcp_resource.ResourceCodec`)
to your tools and tenancy. The base is a working single-tenant, deny-all server:
it authenticates and offers no tools. Override :meth:`map_unexpected_exception`,
:meth:`audit`, and :meth:`throttle` to add exception mapping, an audit trail, and
rate limiting. See ``agents_docs/working_with_hosted_mcp.md``.

The fail-closed "no 500, no leak" guarantee covers a **tool handler** raising:
an unmapped exception becomes a generic ``isError`` result, logged without its
text. It does not wrap the ``throttle``/``audit``/``map_unexpected_exception``
hooks or a non-serialisable result — a fork's own hook that raises will 500, so
keep hooks total and results JSON-serialisable.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import urljoin, urlsplit

import structlog
from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import Http404, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from oauth2_provider.oauth2_backends import get_oauthlib_core

from speedpycom.api.mcp_audience import token_allows_resource
from speedpycom.api.mcp_catalogue import McpContext, ToolCatalogue, ToolError
from speedpycom.api.mcp_host import hostname_of, mcp_hostname
from speedpycom.api.mcp_resource import ResourceCodec

logger = structlog.get_logger(__name__)

MODERN_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED_VERSIONS = (MODERN_VERSION, *LEGACY_VERSIONS)

# JSON-RPC and MCP error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

_META_PREFIX = "io.modelcontextprotocol/"
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Caching hints the specification REQUIRES on every complete result of a listing
# method. `(ttlMs, cacheScope)`. The tool list is `private` (authenticated, and
# its contents depend on the resource); discovery is `public` (same for everyone).
TOOLS_CACHE = (300_000, "private")
DISCOVER_CACHE = (3_600_000, "public")


def _origin_tuple(value):
    """``(scheme, host, port)`` for an origin, or ``None``. A full origin, so
    ``http://`` and ``https://`` of one host are correctly different."""
    if not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    return (scheme, parts.hostname.lower(), port or _DEFAULT_PORTS.get(scheme))


def _json_rpc_error(code, message, *, request_id=None, data=None, status=200):
    body = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        body["error"]["data"] = data
    return JsonResponse(body, status=status)


def _json_rpc_result(request_id, result, *, modern=False, cache=None):
    """One JSON-RPC result. ``resultType`` and the cache hints are added only for
    a modern caller, because older revisions have no such fields."""
    if modern and isinstance(result, dict):
        result = {"resultType": "complete", **result}
        if cache is not None:
            ttl_ms, scope = cache
            result["ttlMs"] = ttl_ms
            result["cacheScope"] = scope
    return JsonResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _tool_error(message, request_id, *, modern=False):
    """An MCP tool failure: a ``200`` the model reads and acts on. ``_meta``
    carries the same text for ChatGPT, which reads that field."""
    return _json_rpc_result(
        request_id,
        {
            "content": [{"type": "text", "text": message}],
            "isError": True,
            "_meta": {"mcp/errorText": message},
        },
        modern=modern,
    )


def _decode_header(value):
    """Decode the ``=?base64?…?=`` sentinel used for odd header values."""
    if value is None:
        return None
    if value.startswith("=?base64?") and value.endswith("?="):
        raw = value[len("=?base64?"): -len("?=")]
        try:
            return base64.b64decode(raw).decode("utf-8")
        except Exception:
            return value
    return value


class MCPEndpointView(View):
    """``POST {base}/mcp[/…]`` — the whole transport.

    Subclass and set :attr:`catalogue` and :attr:`resource_codec`.
    """

    server_name: str = "speedpy"
    instructions: str = ""
    catalogue: ToolCatalogue = ToolCatalogue()
    resource_codec: ResourceCodec = ResourceCodec()

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "MCP_ENABLED", False):
            raise Http404("The hosted MCP endpoint is not enabled.")
        # The route only exists on the MCP host (mcp_host middleware). Checked
        # again here because this view decides an audience, and an audience must
        # never depend on another component having done its job.
        if hostname_of(request.get_host()) != mcp_hostname():
            raise Http404("Not served on this host.")
        return super().dispatch(request, *args, **kwargs)

    # -- HTTP shape ---------------------------------------------------------

    def get(self, request, *args, **kwargs):
        # 2026-07-28 removed the GET stream; answer 405 rather than pretend.
        return HttpResponse(status=405, headers={"Allow": "POST"})

    delete = get
    put = get
    patch = get

    def post(self, request, *args, **kwargs):
        origin_refusal = self._check_origin(request)
        if origin_refusal is not None:
            return origin_refusal

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_rpc_error(PARSE_ERROR, "The body is not valid JSON.")
        if not isinstance(payload, dict):
            return _json_rpc_error(INVALID_REQUEST, "Send one JSON-RPC message, not a batch.")
        if payload.get("jsonrpc") != "2.0":
            return _json_rpc_error(INVALID_REQUEST, 'jsonrpc must be "2.0".', status=400)

        method = payload.get("method")
        request_id = payload.get("id")
        if not isinstance(method, str) or not method:
            return _json_rpc_error(
                INVALID_REQUEST, "method must be a string.", request_id=request_id, status=400
            )
        if request_id is not None and not isinstance(request_id, (str, int)):
            return _json_rpc_error(INVALID_REQUEST, "id must be a string or a number.", status=400)
        params = payload.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _json_rpc_error(INVALID_PARAMS, "params must be an object.", request_id=request_id)
        meta = params.get("_meta")
        if meta is not None and not isinstance(meta, dict):
            return _json_rpc_error(INVALID_PARAMS, "params._meta must be an object.", request_id=request_id)

        # A notification carries no id and expects no body.
        if request_id is None:
            if method.startswith("notifications/"):
                return HttpResponse(status=202)
            return _json_rpc_error(INVALID_REQUEST, f"{method} is a request and needs an id.", status=400)

        resource = self._resource(kwargs)
        header_version = request.headers.get("MCP-Protocol-Version")
        body_version = (meta or {}).get(_META_PREFIX + "protocolVersion")
        modern = body_version == MODERN_VERSION or header_version == MODERN_VERSION

        if modern:
            mismatch = self._check_modern_headers(request, method, params, request_id)
            if mismatch is not None:
                return mismatch
            if body_version not in SUPPORTED_VERSIONS:
                return _json_rpc_error(
                    UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
                    request_id=request_id,
                    data={"supported": list(SUPPORTED_VERSIONS), "requested": body_version},
                    status=400,
                )
        elif header_version and header_version not in SUPPORTED_VERSIONS:
            return _json_rpc_error(
                UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
                request_id=request_id,
                data={"supported": list(SUPPORTED_VERSIONS), "requested": header_version},
                status=400,
            )

        if method == "initialize":
            return self._initialize(params, request_id)
        if method == "server/discover":
            return _json_rpc_result(request_id, self._discover(), modern=modern, cache=DISCOVER_CACHE)
        if method == "ping":
            return _json_rpc_result(request_id, {}, modern=modern)
        if method in ("tools/list", "tools/call"):
            return self._authenticated(request, method, params, request_id, resource, modern)

        return _json_rpc_error(
            METHOD_NOT_FOUND, f"There is no method {method!r}.",
            request_id=request_id,
            # 404 for modern (how a modern client tells the eras apart); a 200 for
            # legacy, which reads a 404 as the endpoint being gone.
            status=404 if modern else 200,
        )

    # -- seams --------------------------------------------------------------

    def _resource(self, kwargs):
        """Build the resource this call is bound to from the URL kwargs.

        The single-tenant default takes no kwargs and returns the root resource.
        A tenancy-aware subclass overrides this (or relies on its ``resource_class``
        fields matching the route kwargs).
        """
        return self.resource_codec.resource_class(**kwargs)

    def map_unexpected_exception(self, exc, name):
        """Map an exception a handler raised (other than :class:`ToolError`) to a
        tool-error message, or return ``None`` to use the generic fail-closed
        message. Override to translate your own domain exceptions."""
        return None

    def audit(self, request, ctx, *, tool, outcome, request_id):
        """Record one tool call. No-op by default; override to persist an audit
        event (tool, resource, user, outcome, request id)."""

    def throttle(self, request, ctx):
        """Return a JSON-RPC refusal response to rate-limit this call, or ``None``
        to allow it. No-op by default."""
        return None

    def server_icon_url(self):
        """Absolute URL of the server icon for ``serverInfo.icons``, or ``""``.

        ``MCP_SERVER_ICON_URL`` wins; otherwise ``MCP_SERVER_ICON_STATIC`` is
        resolved through staticfiles and made absolute against ``SITE_URL`` (the
        icon is served from the app, not the MCP host)."""
        override = getattr(settings, "MCP_SERVER_ICON_URL", "") or ""
        if override:
            return override
        static_path = getattr(settings, "MCP_SERVER_ICON_STATIC", "") or ""
        if not static_path:
            return ""
        try:
            path = staticfiles_storage.url(static_path)
        except Exception:
            return ""
        if path.startswith(("http://", "https://")):
            return path
        site = getattr(settings, "SITE_URL", "") or ""
        return urljoin(site, path) if site else ""

    # -- helpers ------------------------------------------------------------

    def _check_origin(self, request):
        """DNS-rebinding defence. Only applies when an ``Origin`` is present
        (browsers send one; the agents this exists for do not)."""
        origin = request.headers.get("Origin")
        if not origin:
            return None
        if _origin_tuple(origin) == _origin_tuple(settings.MCP_BASE_URL):
            return None
        return _json_rpc_error(INVALID_REQUEST, "This origin may not call the MCP endpoint.", status=403)

    def _check_modern_headers(self, request, method, params, request_id):
        """``2026-07-28`` mirrors body fields into headers and demands they agree
        — a load balancer routing on the header while the server runs the body is
        a confused-deputy shape, so a mismatch is refused."""
        version_header = request.headers.get("MCP-Protocol-Version")
        body_version = (params.get("_meta") or {}).get(_META_PREFIX + "protocolVersion")
        method_header = request.headers.get("Mcp-Method")
        name_header = _decode_header(request.headers.get("Mcp-Name"))

        problems = []
        if not version_header:
            problems.append("MCP-Protocol-Version is missing")
        elif version_header != body_version:
            problems.append("MCP-Protocol-Version does not match the body")
        if not method_header:
            problems.append("Mcp-Method is missing")
        elif method_header != method:
            problems.append("Mcp-Method does not match the body")
        if method == "tools/call":
            body_name = params.get("name")
            if name_header is None:
                problems.append("Mcp-Name is missing")
            elif name_header != body_name:
                problems.append("Mcp-Name does not match the body")

        if not problems:
            return None
        return _json_rpc_error(
            HEADER_MISMATCH, "Header mismatch: " + "; ".join(problems),
            request_id=request_id, status=400,
        )

    def _server_info(self):
        info = {
            "name": self.server_name,
            "version": getattr(settings, "SPECTACULAR_SETTINGS", {}).get("VERSION", "1.0.0"),
        }
        icon = self.server_icon_url()
        if icon:
            info["icons"] = [{"src": icon, "mimeType": "image/png", "sizes": "256x256"}]
        return info

    def _discover(self):
        return {
            "resultType": "complete",
            "supportedVersions": list(SUPPORTED_VERSIONS),
            "capabilities": {"tools": {}},
            "instructions": self.instructions,
            "_meta": {_META_PREFIX + "serverInfo": self._server_info()},
        }

    def _initialize(self, params, request_id):
        """The legacy handshake. No session id is minted or echoed."""
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else LEGACY_VERSIONS[0]
        return _json_rpc_result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": self._server_info(),
                "instructions": self.instructions,
            },
        )

    # -- authentication -----------------------------------------------------

    def _resource_metadata_url(self, resource):
        return (
            f"{settings.MCP_BASE_URL}/.well-known/oauth-protected-resource/"
            f"{resource.path}"
        )

    def _challenge(self, resource, *, error, description, scopes, status):
        """An RFC 6750 challenge with RFC 9728's pointer to the metadata. ``error``
        is omitted for a request that carried no credentials at all."""
        params = []
        if error:
            params.append(f'error="{error}"')
            params.append(f'error_description="{description}"')
        params.append(f'resource_metadata="{self._resource_metadata_url(resource)}"')
        params.append(f'scope="{" ".join(scopes)}"')
        response = JsonResponse({"error": error, "error_description": description}, status=status)
        response["WWW-Authenticate"] = "Bearer " + ", ".join(params)
        return response

    def _authenticate(self, request, resource):
        """The (user, token), or a challenge response. Never a tool error."""
        # Validate the bearer token as DOT's DRF auth does, but against the plain
        # Django request (the body is JSON-RPC, with no DRF parser configured).
        valid, oauth_request = get_oauthlib_core().verify_request(request, scopes=[])
        user = getattr(oauth_request, "user", None) if valid else None
        if user is None or not user.is_authenticated:
            presented = bool(request.headers.get("Authorization"))
            return None, self._challenge(
                resource,
                error="invalid_token" if presented else "",
                description="That access token is not usable here.",
                scopes=self.catalogue.connector_scopes,
                status=401,
            )
        token = oauth_request.access_token
        resource_url = self.resource_codec.build_url(resource)
        if not token_allows_resource(token, resource_url):
            logger.warning(
                "mcp_token_rejected",
                reason="unbound" if not getattr(token, "resource", None) else "wrong_resource",
                resource=resource_url,
            )
            return None, self._challenge(
                resource,
                error="invalid_token",
                description=(
                    "This token was not issued for this MCP URL. Authorize again, "
                    "sending the resource parameter from the protected-resource metadata."
                ),
                scopes=self.catalogue.connector_scopes,
                status=401,
            )
        return (user, token), None

    def _authenticated(self, request, method, params, request_id, resource, modern):
        identity, refusal = self._authenticate(request, resource)
        if refusal is not None:
            return refusal
        user, token = identity
        ctx = McpContext(user=user, auth=token, resource=resource)

        throttled = self.throttle(request, ctx)
        if throttled is not None:
            return throttled

        if method == "tools/list":
            return _json_rpc_result(
                request_id, {"tools": self.catalogue.definitions(resource)},
                modern=modern, cache=TOOLS_CACHE,
            )

        name = params.get("name")
        tool = self.catalogue.get(name) if isinstance(name, str) else None
        if tool is None:
            return _json_rpc_error(
                INVALID_PARAMS, f"There is no tool called {name!r}.",
                request_id=request_id, data={"available": sorted(self.catalogue._by_name)},
            )
        raw_arguments = params.get("arguments")
        if raw_arguments is not None and not isinstance(raw_arguments, dict):
            # A malformed request, not a tool that failed: arguments is a JSON
            # object or nothing, never an array or scalar.
            return _json_rpc_error(
                INVALID_PARAMS, "arguments must be an object.", request_id=request_id
            )

        # Scope preflight, before the tool runs, so an insufficient token gets the
        # challenge the spec asks for instead of a tool error nobody can act on.
        if not self.catalogue.has_scope(ctx, tool.scope):
            return self._challenge(
                resource, error="insufficient_scope",
                description=f"{name} needs the {tool.scope} scope.",
                scopes=(tool.scope,), status=403,
            )

        try:
            result = self.catalogue.call(ctx, name, raw_arguments)
        except ToolError as exc:
            self.audit(request, ctx, tool=name, outcome="tool_error", request_id=request_id)
            return _tool_error(str(exc), request_id, modern=modern)
        except Exception as exc:
            mapped = self.map_unexpected_exception(exc, name)
            if mapped is not None:
                self.audit(request, ctx, tool=name, outcome="refused", request_id=request_id)
                return _tool_error(mapped, request_id, modern=modern)
            # Fail closed: a tool argument is attacker-shaped, and an unhandled
            # error must not become a 500. Logged with the id, reported generically.
            logger.exception("mcp_tool_failed", tool=name, resource=resource.path)
            self.audit(request, ctx, tool=name, outcome="error", request_id=request_id)
            return _tool_error(
                f"{name} could not complete. The problem has been logged.",
                request_id, modern=modern,
            )
        self.audit(request, ctx, tool=name, outcome="ok", request_id=request_id)
        return _json_rpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "structuredContent": result,
                "isError": False,
            },
            modern=modern,
        )
