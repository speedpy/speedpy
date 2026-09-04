"""DOT validator with the CIMD public downgrade for one-click MCP connectors.

Wired via ``OAUTH2_PROVIDER["OAUTH2_VALIDATOR_CLASS"]`` **only when MCP is
enabled**; unwired it is inert. The RFC 8707 audience rules are separate
(``speedpycom.api.mcp_audience``) and wired via
``RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR``.

--- The CIMD public downgrade -------------------------------------------------

Client ID Metadata Documents (CIMD) let a client identify itself by an HTTPS URL
it hosts, so the big directories can connect without dynamic registration. Two
of them declare a confidential ``token_endpoint_auth_method`` that DOT's stock
CIMD path rejects: ChatGPT declares ``private_key_jwt`` and Claude's document
lists an extra ``jwt-bearer`` grant. DOT then 400s the whole document and the
native one-click flow fails at the authorize step.

This validator makes one **deliberate, allowlisted** exception: for a CIMD
``client_id`` on ``MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS`` it resolves the
document itself and persists the client as **public** (PKCE-protected) instead
of rejecting the self-asserted confidential declaration. This is a compatibility
policy, not standards negotiation: it is acceptable only because an
authorization-code client with a **fixed redirect URI** plus **mandatory S256
PKCE** does not need client authentication to be safe, and it is bound to an
explicit client_id allowlist rather than a heuristic. **An empty allowlist (the
default) restores stock behaviour.**

The apparatus mirrors DOT's private ``cimd`` internals (grant-type resolution,
kwargs validation, fetch/validate/upsert, per-URL failure backoff, in-flight
cap). It is pinned to DOT ``<4.0`` and guarded by parity tests, so a DOT upgrade
that changes the mirrored logic is caught here rather than in production.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import threading
from datetime import timedelta

import jwt
import structlog
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from oauth2_provider.cimd import CIMDError
from oauth2_provider.models import AbstractApplication, get_application_model
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.settings import oauth2_settings

log = logging.getLogger(__name__)

__all__ = ["SpeedPyOAuth2Validator", "build_public_downgrade_kwargs"]

# RFC 7591 grant_type name -> DOT authorization_grant_type. A local copy rather
# than an import of DOT's private ``cimd.GRANT_TYPE_MAP``; a parity test pins it
# against DOT's own resolution so a DOT upgrade that changes the mapping is
# caught here rather than in production.
_GRANT_TYPE_MAP = {
    "authorization_code": AbstractApplication.GRANT_AUTHORIZATION_CODE,
    "implicit": AbstractApplication.GRANT_IMPLICIT,
}
# ``refresh_token`` is handled by DOT alongside authorization_code, not a
# standalone grant choice.
_IGNORED_GRANT_TYPES = frozenset({"refresh_token"})


def _public_downgrade_client_ids():
    """The CIMD client_id URLs allowed to be downgraded to a public client.

    Read live from settings so a test's ``override_settings`` takes effect and an
    empty allowlist reliably means "off" (stock behaviour).
    """
    return frozenset(getattr(settings, "MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS", ()) or ())


# Failure backoff for the downgrade fetch. The stock CIMD path installs its own
# backoff (``cimd.resolve_cimd_application``), but this override resolves an
# allowlisted URL *before* that path and does not delegate to it, so it needs a
# backoff of its own — otherwise, while the (allowlisted, trusted) remote is
# down, every unauthenticated authorize/token request bearing that client_id
# would trigger a fresh outbound fetch and tie up a worker. Keyed by a hash of
# the client_id so an untrusted 255-char id can never overflow a cache backend's
# key limit; reuses DOT's ``CIMD_FAILURE_BACKOFF_SECONDS`` for the duration.
_DOWNGRADE_BACKOFF_PREFIX = "speedpycom:cimd_public_downgrade:backoff:"


def _downgrade_backoff_key(client_id):
    digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
    return _DOWNGRADE_BACKOFF_PREFIX + digest


# Non-blocking in-flight cap for the downgrade fetch, mirroring DOT's own
# ``cimd._fetch_slot``. The backoff bounds *sequential* retries once a fetch has
# failed; this bounds a *parallel* first-sight burst (before any backoff is set,
# or after it expires), so a flood of concurrent authorize/token requests bearing
# the allowlisted client_id cannot hold every worker for the fetch timeout while
# the remote is down. Per-process BoundedSemaphore, rebuilt when the configured
# size changes (e.g. between tests). Reuses DOT's ``CIMD_MAX_CONCURRENT_FETCHES``
# (0/None disables the cap).
_downgrade_semaphore_lock = threading.Lock()
_downgrade_semaphore = None
_downgrade_semaphore_size = None


def _downgrade_fetch_semaphore():
    global _downgrade_semaphore, _downgrade_semaphore_size
    size = oauth2_settings.CIMD_MAX_CONCURRENT_FETCHES
    if not size:
        return None
    with _downgrade_semaphore_lock:
        if _downgrade_semaphore is None or _downgrade_semaphore_size != size:
            _downgrade_semaphore = threading.BoundedSemaphore(size)
            _downgrade_semaphore_size = size
        return _downgrade_semaphore


@contextlib.contextmanager
def _downgrade_fetch_slot():
    """Take a non-blocking in-flight fetch slot.

    Yields True when a slot was taken (or the cap is disabled), False when the
    cap is already full — non-blocking so an over-capacity request fails fast
    rather than queuing and tying up a worker.
    """
    semaphore = _downgrade_fetch_semaphore()
    acquired = semaphore is None or semaphore.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired and semaphore is not None:
            semaphore.release()


def _bounded(value, limit=80):
    """Coerce a log value to a bounded string so an attacker-controlled field (a
    giant or non-string ``alg``/``kid``/assertion type) can't amplify a log line.
    ``None`` passes through unchanged."""
    if value is None:
        return None
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


def _correlation_id():
    """The request's structlog ``request_id`` (django-structlog binds it), or
    ``None`` outside a request. Never raises."""
    try:
        return structlog.contextvars.get_contextvars().get("request_id")
    except Exception:
        return None


def _resolve_grant_type(grant_types):
    """Resolve an RFC 7591 grant_types list to a single DOT grant constant.

    Deliberately **more tolerant** than ``oauth2_provider.cimd._resolve_grant_type``,
    which rejects any document declaring more than one non-refresh grant type.
    Real first-party MCP clients declare several: Claude's document lists
    ``authorization_code`` alongside ``urn:ietf:params:oauth:grant-type:jwt-bearer``,
    and DOT's stock resolver 400s the whole document over that extra entry (this
    is the sibling of ChatGPT's ``private_key_jwt`` rejection).

    Because this path only ever runs the interactive **authorization-code** flow
    (public client, fixed redirect URI, mandatory S256 PKCE), the safe resolution
    is to *select* the code grant and leave any other declared grant simply not
    enabled for the client -- never to enable an assertion or implicit grant off
    the back of a self-asserted list. A document that supports **no** grant we
    implement is still refused. This tolerance is only reached through the
    allowlisted acceptance seam below; stock DOT stays strict for every other
    client.
    """
    meaningful = [g for g in grant_types if g not in _IGNORED_GRANT_TYPES]
    supported = [g for g in meaningful if g in _GRANT_TYPE_MAP]
    if "authorization_code" in supported:
        return _GRANT_TYPE_MAP["authorization_code"]
    if len(supported) == 1:
        return _GRANT_TYPE_MAP[supported[0]]
    if not supported:
        raise CIMDError("client metadata declares no supported non-refresh grant type")
    # Several grants we implement, none of them authorization_code: there is no
    # single interactive flow to bind the client to, so refuse rather than guess.
    raise CIMDError("client metadata declares ambiguous non-refresh grant types")


def build_public_downgrade_kwargs(metadata):
    """Convert an allowlisted CIMD document to **public**-Application kwargs.

    Mirrors DOT's ``cimd._build_application_kwargs`` field validation with one
    deliberate difference: it does **not** reject a non-``"none"``
    ``token_endpoint_auth_method``. Accepting a self-asserted confidential method
    and treating the client as public is the whole point of the downgrade.

    A document carrying an actual shared secret is still refused (presence, not
    value) — a real confidential secret is not something we silently downgrade —
    and redirect_uris/client_name are validated exactly as DOT does. Grant types
    are resolved by the tolerant :func:`_resolve_grant_type` above. Raises
    :class:`CIMDError` on invalid metadata.
    """
    # Spec: neither property may appear in a CIMD document (presence, not value).
    if "client_secret" in metadata or "client_secret_expires_at" in metadata:
        raise CIMDError("CIMD client metadata must not include client_secret or client_secret_expires_at")

    redirect_uris = metadata.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not redirect_uris
        or not all(isinstance(u, str) for u in redirect_uris)
    ):
        raise CIMDError("redirect_uris must be a non-empty array of strings")

    grant_types = metadata.get("grant_types", ["authorization_code"])
    if not isinstance(grant_types, list) or not all(isinstance(g, str) for g in grant_types):
        raise CIMDError("grant_types must be an array of strings")

    client_name = metadata.get("client_name", "")
    if not isinstance(client_name, str):
        raise CIMDError("client_name must be a string")

    return {
        "name": client_name,
        "redirect_uris": " ".join(redirect_uris),
        "authorization_grant_type": _resolve_grant_type(grant_types),
    }


def _sanitized_assertion_facts(request):
    """Safe-to-log facts about a token-step ``client_assertion``.

    Never returns the raw assertion, its payload or its signature — only its
    presence, its declared type, and the JWT header ``alg``/``kid``.
    ``jwt.get_unverified_header`` does not verify the signature (it reads the
    header without any key); we take only ``alg``/``kid`` from the header dict and
    never read or log the payload. Every value is passed through :func:`_bounded`,
    because the assertion is attacker-suppliable (any client can post a
    ``client_assertion`` for an allowlisted client_id) — an unbounded
    ``alg``/``kid``/type would be a log-amplification vector.
    """
    assertion = getattr(request, "client_assertion", None)
    facts = {
        "present": bool(assertion),
        "type": _bounded(getattr(request, "client_assertion_type", None)),
        "alg": None,
        "kid": None,
    }
    if assertion:
        try:
            header = jwt.get_unverified_header(assertion)
            facts["alg"] = _bounded(header.get("alg"))
            facts["kid"] = _bounded(header.get("kid"))
        except Exception:
            # A malformed assertion must not break the token step or the log.
            facts["alg"] = "<unparseable>"
    return facts


class SpeedPyOAuth2Validator(OAuth2Validator):
    """DOT validator adding the allowlisted CIMD public downgrade.

    The RFC 8707 audience rules are wired separately via
    ``RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR`` (see
    ``speedpycom.api.mcp_audience``); this subclass only adds the CIMD public
    downgrade to the client-loading seam.
    """

    def _should_public_downgrade(self, client_id, request):
        """Whether this request should resolve *client_id* as a public downgrade.

        True only when the id is allowlisted, CIMD is enabled, no usable cached
        client is already set, and no Application row exists yet. A stored row is
        left to ``super()`` (its ``refresh_if_stale`` keeps the public row on a
        failed re-fetch), which is what lets a later hard transition of that one
        row happen in place without this override re-creating it.
        """
        if not client_id or client_id not in _public_downgrade_client_ids():
            return False
        if not oauth2_settings.CIMD_ENABLED:
            return False
        Application = get_application_model()
        cached = getattr(request, "client", None)
        if (
            isinstance(cached, Application)
            and cached.client_id == client_id
            and cached.is_usable(request)
        ):
            return False
        return not Application.objects.filter(client_id=client_id).exists()

    def _resolve_public_downgrade_application(self, client_id, request):
        """Fetch the allowlisted CIMD document and upsert it as a public client.

        Mirrors ``cimd._fetch_validate_upsert`` — same client_id-match binding,
        non-CIMD collision guard, ``full_clean`` and concurrent-first-sight race
        handling — but persists ``CLIENT_PUBLIC`` for a document DOT would reject.
        Fails closed: any error returns ``None`` (the caller then refuses the
        request after a backoff), never a 500 on the pre-auth path.

        Uses the configured ``CIMD_METADATA_FETCHER`` (which performs the
        URL/IP/SSRF validation); it does not import DOT's underscore-private
        fetch/validate helpers, which are unversioned under the ``<4.0`` pin.
        """
        try:
            return self._upsert_public_downgrade_application(client_id, request)
        except Exception:
            # This runs on the pre-auth authorize/token endpoint against a
            # client-controlled URL. An unexpected error (a custom fetcher raising
            # something other than CIMDError, a DB blip) must degrade to "unknown
            # client", never a 500. Mirrors cimd.resolve_cimd_application.
            log.exception("Unexpected error in CIMD compat for %r", client_id)
            return None

    def _upsert_public_downgrade_application(self, client_id, request):
        """Inner resolver for :meth:`_resolve_public_downgrade_application`.

        Kept separate so the wrapper's broad exception guard is the single
        fail-closed boundary; this body may raise freely.
        """
        Application = get_application_model()
        fetcher = oauth2_settings.CIMD_METADATA_FETCHER()
        try:
            metadata, max_age = fetcher.fetch(client_id)
        except CIMDError as exc:
            log.info("CIMD compat fetch failed for %r: %r", client_id, exc)
            return None

        # Spec: the document's client_id MUST equal the URL it was fetched from.
        if metadata.get("client_id") != client_id:
            log.info("CIMD compat document client_id does not match %r", client_id)
            return None

        try:
            kwargs = build_public_downgrade_kwargs(metadata)
        except CIMDError as exc:
            log.info("CIMD compat metadata invalid for %r: %r", client_id, exc)
            return None

        try:
            application = Application.objects.get(client_id=client_id)
            if application.registration_source != Application.RegistrationSource.CIMD:
                # A manually provisioned client owns this id; never take it over.
                log.warning("CIMD compat client_id collides with a non-CIMD app: %r", client_id)
                return None
        except Application.DoesNotExist:
            application = Application(client_id=client_id)

        application.user = None
        application.client_type = Application.CLIENT_PUBLIC
        application.registration_source = Application.RegistrationSource.CIMD
        application.cimd_expires_at = timezone.now() + timedelta(seconds=max_age)
        for field, value in kwargs.items():
            setattr(application, field, value)

        try:
            application.full_clean(exclude=["client_secret"], validate_unique=False)
        except ValidationError as exc:
            log.info(
                "CIMD compat validation failed for %r: %s",
                client_id,
                "; ".join(exc.messages),
            )
            return None

        try:
            # A savepoint, not the request transaction. Production runs Postgres
            # with ATOMIC_REQUESTS, so an IntegrityError raised straight into the
            # request's transaction would mark it broken and make the recovery
            # query below raise TransactionManagementError instead of loading the
            # winner. Wrapping only the insert lets the collision roll back to here
            # and the recovery run on a healthy connection.
            with transaction.atomic():
                application.save()
        except IntegrityError as exc:
            # Concurrent first-sight of the same URL: another request won.
            try:
                application = Application.objects.get(client_id=client_id)
            except Application.DoesNotExist:
                log.info("CIMD compat row vanished during a concurrent upsert: %r", client_id)
                return None
            if application.registration_source != Application.RegistrationSource.CIMD:
                log.warning("CIMD compat client_id collides with a non-CIMD app: %r", client_id)
                return None
            log.info("CIMD compat lost a concurrent upsert race, reusing winner: %r (%r)", client_id, exc)
        return application

    def _load_application(self, client_id, request):
        """Resolve an allowlisted CIMD client as public before stock resolution.

        Intercepting **before** ``super()`` matters: calling stock first would
        fetch the document, have DOT reject the confidential method, and install
        the per-URL failure backoff (``cimd.py``) — then our resolver would fight
        that backoff.

        Once a client_id is eligible (allowlisted, CIMD on, no usable cached
        client, no stored row), this method owns it end to end and does **not**
        fall through to ``super()``: falling through would fetch the document a
        second time, and — because our path runs first — would keep fetching on
        every request while the remote is down. So an eligible request either
        succeeds here, or is refused after a bounded failure backoff. Everything
        else (a stored row, a normal client, plain ``none`` CIMD such as Claude)
        goes to ``super()`` unchanged.
        """
        if self._should_public_downgrade(client_id, request):
            if cache.get(_downgrade_backoff_key(client_id)):
                # Recent failure for this URL; refuse without a fresh fetch.
                return None
            with _downgrade_fetch_slot() as acquired:
                if not acquired:
                    # Over capacity, not backed off: refuse without a fetch and
                    # without recording a failure (the URL may be perfectly fine).
                    log.warning(
                        "CIMD compat fetch skipped for %r: in-flight cap reached",
                        client_id,
                    )
                    return None
                application = self._resolve_public_downgrade_application(client_id, request)
                if application is not None and application.is_usable(request):
                    request.client = application
                    return request.client
                # Eligible but declined: back off, and do not re-fetch via stock.
                cache.set(
                    _downgrade_backoff_key(client_id),
                    True,
                    oauth2_settings.CIMD_FAILURE_BACKOFF_SECONDS,
                )
                return None
        return super()._load_application(client_id, request)

    def authenticate_client_id(self, client_id, request, *args, **kwargs):
        """Record whether a presented assertion was ignored at the token step.

        For a public client oauthlib authenticates the code exchange here and
        **never inspects ``client_assertion``**: a token issued to this client
        proves PKCE, not that the client accepted public auth. We call ``super()``
        first, then — only when the loaded client is genuinely the public CIMD
        downgrade (not a manual row or a hard confidential transition of the same
        id) — log the sanitized facts plus the branch, outcome and correlation id.
        Sanitized facts only; the raw body, code, verifier and assertion are never
        logged.
        """
        authenticated = super().authenticate_client_id(client_id, request, *args, **kwargs)
        if client_id in _public_downgrade_client_ids():
            client = getattr(request, "client", None)
            Application = get_application_model()
            if (
                isinstance(client, Application)
                and client.client_type == Application.CLIENT_PUBLIC
                and client.registration_source == Application.RegistrationSource.CIMD
            ):
                facts = _sanitized_assertion_facts(request)
                log.info(
                    "CIMD compat token step: client_id=%r grant_type=%r "
                    "branch=public_client_id outcome=%s assertion_present=%s "
                    "assertion_type=%r jwt_alg=%r jwt_kid=%r correlation_id=%r",
                    client_id,
                    _bounded(getattr(request, "grant_type", None)),
                    "authenticated" if authenticated else "refused",
                    facts["present"],
                    facts["type"],
                    facts["alg"],
                    facts["kid"],
                    _correlation_id(),
                )
        return authenticated
