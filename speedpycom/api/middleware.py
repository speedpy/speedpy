"""API middleware for request correlation IDs, rate-limit headers, and audit logging."""

import re
import uuid

import structlog
from django.conf import settings


_VALID_REQUEST_ID = re.compile(r"^[\w\-]{1,128}$")


class RequestIDMiddleware:
    """
    Ensure every API response carries an ``X-Request-ID`` header.

    - If the client sends a valid ``X-Request-ID``, it is accepted and echoed.
    - If the header is missing, django_structlog's ``RequestMiddleware``
      generates one automatically (it runs earlier in the stack).
    - If the client sends an invalid ID (wrong length or characters), it is
      silently replaced with a generated UUID to avoid breaking clients.

    This middleware reads the ``request_id`` that django_structlog already
    bound into contextvars, so it always matches what appears in logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Validate inbound header — replace bad values before the request
        # proceeds further.  django_structlog has already read the header in
        # its prepare() method, so we also rebind the contextvars if we
        # replaced the value.
        raw = request.META.get("HTTP_X_REQUEST_ID", "")
        if raw and not _VALID_REQUEST_ID.match(raw):
            new_id = str(uuid.uuid4())
            request.META["HTTP_X_REQUEST_ID"] = new_id
            structlog.contextvars.bind_contextvars(request_id=new_id)

        response = self.get_response(request)

        # Read the authoritative request_id from structlog context (set by
        # django_structlog or our override above).
        ctx = structlog.contextvars.get_contextvars()
        request_id = ctx.get("request_id")
        if request_id:
            response["X-Request-ID"] = request_id

        return response


class RateLimitHeadersMiddleware:
    """
    Read rate-limit metadata attached by SpeedPy throttle classes and emit
    standard ``X-RateLimit-*`` headers on every API response.

    Must be placed **after** DRF processes the request (i.e. in the response
    phase).  Since DRF views run inside Django's middleware stack, any
    middleware position works — the headers are set in the response phase.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        headers = getattr(request, "_rate_limit_headers", None)
        if headers:
            # Use the most restrictive bucket (lowest remaining).
            best = min(headers, key=lambda h: h["remaining"])
            response["X-RateLimit-Limit"] = best["limit"]
            response["X-RateLimit-Remaining"] = best["remaining"]
            response["X-RateLimit-Reset"] = best["reset"]
        return response


_audit_logger = structlog.get_logger("speedpycom.api.audit")

# Prefix used to scope audit logging to API paths only.
_API_PATH_PREFIX = "/api/"


def _get_client_ip(request):
    """Return the best-guess client IP from X-Forwarded-For or REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _resolve_token_meta(request):
    """Extract token_type, token_id, and scopes from the authenticated request."""
    auth = getattr(request, "auth", None)
    if auth is None:
        return "", "", []

    # PAT — auth is a PersonalAccessToken instance
    from usermodel.models import PersonalAccessToken

    if isinstance(auth, PersonalAccessToken):
        return "pat", str(auth.id), auth.scopes or []

    # OAuth2 (django-oauth-toolkit) — auth is an AccessToken instance
    try:
        from oauth2_provider.models import AccessToken

        if isinstance(auth, AccessToken):
            return "oauth2", str(auth.pk), auth.scope.split() if auth.scope else []
    except ImportError:
        pass

    # JWT — auth is a rest_framework_simplejwt validated token (dict-like)
    if hasattr(auth, "payload"):
        return "jwt", auth.get("jti", ""), []

    # Session / unknown
    return "session", "", []


class ApiAccessLogMiddleware:
    """
    Write per-request audit records when ``SPEEDPY_API_ACCESS_LOG_ENABLED``
    is ``True``.  Only logs requests under ``/api/``.

    Must run **after** authentication (DRF authenticates inside the view, so
    this middleware captures the response phase *after* authentication has
    occurred).  Audit writes are fire-and-forget: failures are logged but
    never break the response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not getattr(settings, "SPEEDPY_API_ACCESS_LOG_ENABLED", False):
            return response

        if not request.path.startswith(_API_PATH_PREFIX):
            return response

        try:
            self._record(request, response)
        except Exception:
            _audit_logger.exception("audit_log_write_failed")

        return response

    def _record(self, request, response):
        from usermodel.models import ApiAccessLog, _truncate_ip

        token_type, token_id, scopes = _resolve_token_meta(request)
        user = getattr(request, "user", None)
        if user and not user.is_authenticated:
            user = None

        ctx = structlog.contextvars.get_contextvars()
        request_id = ctx.get("request_id", "")

        ApiAccessLog.objects.create(
            user=user,
            token_type=token_type,
            token_id=token_id,
            scopes=scopes,
            method=request.method,
            path=request.path[:2048],
            status_code=response.status_code,
            ip_truncated=_truncate_ip(_get_client_ip(request)),
            request_id=request_id,
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:512],
        )
