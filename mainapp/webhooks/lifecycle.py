"""Endpoint lifecycle: is a subscription still allowed to receive deliveries,
and the one safe way to deactivate one.

Webhook endpoints created through the API carry a connection identity
(``created_by``, ``application``, ``token_family``, ``origin`` on
:class:`~mainapp.models.webhooks.WebhookEndpoint`). Dispatch fails **closed** on
that identity: a delivery is created and sent only while the connection behind
it is still valid — the team is active and entitled, the creating member still
belongs to the team, and (for OAuth-created endpoints) the OAuth connection is
still live. A missing reference is a failure, never a skip, so a deleted
creator/application (``SET_NULL`` FKs) stops deliveries rather than waving them
through.

The team-entitlement half is pluggable so a downstream project can gate
endpoints on its own plan feature (e.g. "API access") without forking this file:
set ``SPEEDPY_WEBHOOK_TEAM_ELIGIBLE`` to the dotted path of a ``(team) -> bool``
callable. When unset, every active team is eligible (the boilerplate default).
"""

import structlog
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

logger = structlog.get_logger(__name__)


# --- Team entitlement seam ---------------------------------------------------

_UNSET = object()
# Cache the resolved callable keyed by the dotted path, so a normal run resolves
# it once but ``override_settings(SPEEDPY_WEBHOOK_TEAM_ELIGIBLE=...)`` in tests
# takes effect immediately (the key changes → re-resolve).
_team_eligible_cache = {"dotted": _UNSET, "fn": None}


def _load_team_eligible():
    """Resolve the configured ``(team) -> bool`` eligibility callable, or None."""
    dotted = getattr(settings, "SPEEDPY_WEBHOOK_TEAM_ELIGIBLE", None)
    if _team_eligible_cache["dotted"] != dotted:
        _team_eligible_cache["dotted"] = dotted
        _team_eligible_cache["fn"] = import_string(dotted) if dotted else None
    return _team_eligible_cache["fn"]


def reset_team_eligible_cache():
    """Test hook: forget the resolved callable (rarely needed now the cache is
    keyed on the setting value)."""
    _team_eligible_cache["dotted"] = _UNSET
    _team_eligible_cache["fn"] = None


def team_is_eligible(team) -> bool:
    """Whether ``team`` may hold webhook endpoints at all.

    Active teams pass unless a project-configured feature check refuses. The
    check applies to every endpoint, dashboard-created ones included: webhooks
    are the API, and a downgrade stops them the same day.
    """
    if team is None or not team.is_active:
        return False
    fn = _load_team_eligible()
    if fn is None:
        return True
    return bool(fn(team))


# --- Active-endpoint cap -----------------------------------------------------

DEFAULT_MAX_ACTIVE_ENDPOINTS_PER_TEAM = 50


def max_active_endpoints_per_team() -> int:
    return int(
        getattr(
            settings,
            "WEBHOOK_MAX_ACTIVE_ENDPOINTS_PER_TEAM",
            DEFAULT_MAX_ACTIVE_ENDPOINTS_PER_TEAM,
        )
    )


def team_at_endpoint_cap(team) -> bool:
    """Whether ``team`` already has the maximum number of active endpoints."""
    from mainapp.models.webhooks import WebhookEndpoint

    return (
        WebhookEndpoint.objects.filter(team=team, is_active=True).count()
        >= max_active_endpoints_per_team()
    )


def billing_blocks_new_records(team) -> bool:
    """Whether billing state forbids creating new records for ``team`` right now.

    True during grace/disabled while billing is enabled — the same rule the rest
    of the app uses for record-creating mutations. Applies to session and token
    callers alike (grace means "no new content"), so both the API and the
    server-rendered views consult it.
    """
    from mainapp.billing.state import ENABLED, get_billing_state, is_billing_enabled

    return is_billing_enabled() and get_billing_state(team) != ENABLED


# --- OAuth connection liveness (mirrors DOT's own refresh usability) ---------

def _oauth_family_alive(application, token_family, user) -> bool:
    """Whether the OAuth connection (one refresh-token family) is still live.

    Mirrors ``django-oauth-toolkit``'s own refresh-token usability rule
    (``OAuth2Validator.validate_refresh_token``): a live, actively-used refresh
    token is always paired with an access token, its lifetime slides with that
    access token's expiry, and reuse-protection revokes the whole family. So the
    family is alive iff a non-revoked refresh token in it has a linked access
    token that has not passed ``REFRESH_TOKEN_EXPIRE_SECONDS`` beyond its own
    expiry. A fresh, never-refreshed connection is covered by the same rule (its
    access token is unexpired). A null application or family fails closed.
    """
    if application is None or token_family is None or user is None:
        return False

    from oauth2_provider.models import (
        get_refresh_token_model,
        refresh_token_expire_timedelta,
    )

    RefreshToken = get_refresh_token_model()
    now = timezone.now()
    expire_delta = refresh_token_expire_timedelta()

    # Bind to the creator too: a live family must belong to the member who
    # created the endpoint, not merely to the same application.
    candidates = (
        RefreshToken.objects.filter(
            application=application,
            token_family=token_family,
            user_id=user,
            revoked__isnull=True,
        )
        .exclude(access_token__isnull=True)
        .select_related("access_token")
    )
    for rt in candidates:
        access_token = rt.access_token
        if access_token is None:
            continue
        if expire_delta and access_token.expires + expire_delta <= now:
            continue
        return True
    return False


# --- The deliverability rule -------------------------------------------------

def endpoint_is_deliverable(endpoint) -> tuple[bool, str]:
    """Return ``(deliverable, reason)`` for one endpoint.

    Evaluated at dispatch time (before a delivery row is created) and again in
    the delivery task right before the POST, because the row is enqueued only on
    commit and a revocation in that window would otherwise still send. This is
    race *minimisation*, not an instant guarantee — the window is the queue
    latency.
    """
    team = endpoint.team
    Origin = endpoint.Origin

    # 0) Origin must be a value we know how to reason about. `choices` is not a
    #    DB constraint and saves do not run full_clean(), so an invalid or a
    #    future origin must fail closed rather than fall through to "deliver".
    if endpoint.origin not in (
        Origin.DASHBOARD,
        Origin.LEGACY,
        Origin.API_TOKEN,
        Origin.OAUTH,
    ):
        return False, "invalid_origin"

    # 1) Every endpoint: active, entitled team.
    if not team_is_eligible(team):
        return False, "team_ineligible"

    # 2) Token/OAuth endpoints need a live creating member. Dashboard and legacy
    #    (pre-connection-identity) rows are grandfathered to rule 1 only.
    if endpoint.origin in (Origin.API_TOKEN, Origin.OAUTH):
        if endpoint.created_by_id is None:
            return False, "creator_missing"
        from mainapp.models import TeamMembership

        membership = (
            TeamMembership.objects.filter(
                team=team,
                user_id=endpoint.created_by_id,
                team__is_active=True,
            )
            .exclude(access_expires_at__lte=timezone.now())
            .first()
        )
        if membership is None:
            return False, "creator_not_a_member"

    # 3) OAuth endpoints need a live OAuth connection.
    if endpoint.origin == Origin.OAUTH:
        if not _oauth_family_alive(
            endpoint.application, endpoint.token_family, endpoint.created_by_id
        ):
            return False, "oauth_connection_revoked"

    return True, ""


# --- The one safe deactivation path -----------------------------------------

def deactivate_endpoint(
    endpoint, *, reason: str, expected_url: str | None = None, clear_events: bool = False
) -> bool:
    """Deactivate an endpoint with a compare-and-set; return whether it flipped.

    A single ``UPDATE ... WHERE pk=... AND is_active=true [AND url=expected_url]``
    so a concurrent PATCH that changed the URL (a re-pointed endpoint) is not
    silently turned off by a stale ``410 Gone`` from the old subscriber. A
    ``QuerySet.update`` bypasses ``auto_now``, so ``updated_at`` is set
    explicitly.
    """
    from mainapp.models.webhooks import WebhookEndpoint

    filters = {"pk": endpoint.pk, "is_active": True}
    if expected_url is not None:
        filters["url"] = expected_url

    fields = {"is_active": False, "updated_at": timezone.now()}
    if clear_events:
        fields["events"] = []

    flipped = WebhookEndpoint.objects.filter(**filters).update(**fields)
    if flipped:
        # Keep the in-memory instance consistent for callers that reuse it.
        endpoint.is_active = False
        if clear_events:
            endpoint.events = []
        logger.info(
            "webhook_endpoint_deactivated",
            endpoint_id=str(endpoint.pk),
            team_id=str(endpoint.team_id),
            reason=reason,
        )
    return bool(flipped)
