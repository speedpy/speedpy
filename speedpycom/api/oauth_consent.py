"""The hardened OAuth consent screen for hosted MCP.

The scope grant is the security boundary of the whole hosted MCP feature, and
this page is where a person decides it. Everything here exists because DOT's
stock screen would say something misleading. It is wired at ``/o/authorize/``
only when MCP is enabled; otherwise DOT's stock view runs.

**It names the client by its address, not by its own claim.** Client ID Metadata
Documents let a client identify itself with an HTTPS URL it hosts. That document
is entirely self-asserted — ``client_name`` is whatever the author typed — and
DOT copies it onto the application record, where the stock template renders it as
the page heading. A hostile document claiming ``"client_name": "Acme Official"``
would produce a consent screen on your own domain inviting somebody to authorise
it. So a CIMD client is introduced by the **host of its client_id URL**, which it
cannot forge; its self-asserted name appears only as a secondary, labelled claim.

**It says what the grant covers.** A token is bound to one MCP resource (RFC
8707). What that resource means is your tenancy model, so :meth:`describe_resource`
is a seam: the single-tenant default calls it "your account"; a team/project
subclass overrides it.

**It asks again when the resource changes.** ``REQUEST_APPROVAL_PROMPT`` is
``auto`` and the library's skip compares the user, application and scopes — not
the resource. Without the override here, someone who once approved a client for
one resource would silently hand it another.

**It fails closed.** A consent screen whose job is to show *who* is asking and
*what* they may do must refuse — not render an Authorize button over blanks — when
either is missing or the request cannot be validated at all.
"""

from urllib.parse import urlsplit

from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model
from oauth2_provider.views import AuthorizationView

from speedpycom.api.mcp_resource import ResourceCodec

__all__ = ["ConsentAuthorizationView"]


def _client_host(client_id):
    """Host of a CIMD ``client_id`` URL, or ``""`` for an ordinary client."""
    if not isinstance(client_id, str) or not client_id.startswith("https://"):
        return ""
    try:
        return (urlsplit(client_id).hostname or "").lower()
    except ValueError:
        return ""


def _loopback(uri):
    host = urlsplit(uri).hostname if uri else None
    return host in {"localhost", "127.0.0.1", "::1"}


class ConsentAuthorizationView(AuthorizationView):
    """``/o/authorize/`` with an honest heading and a resource-aware skip.

    Subclass and override :meth:`describe_resource` (and set
    :attr:`resource_codec` to your grammar) to describe team/project resources.
    """

    resource_codec = ResourceCodec()

    def _requested_resources(self):
        """The ``resource`` values on this request, as a normalised list."""
        raw = self.request.GET.getlist("resource") or []
        if not raw:
            single = self.request.GET.get("resource")
            raw = [single] if single else []
        return sorted({value for value in raw if value})

    def get(self, request, *args, **kwargs):
        # Stashed before super(), because its auto-approval branch can return a
        # redirect without ever reaching get_context_data.
        self._resources = self._requested_resources()
        if self._resources and not self._already_approved(request):
            # The library skips consent on a previous approval for the same user,
            # application and scopes — it has no idea about resources. It reads the
            # prompt mode from the query string before that decision, so asking
            # again is a matter of saying so there.
            request.GET = request.GET.copy()
            request.GET["approval_prompt"] = "force"
        return super().get(request, *args, **kwargs)

    def _already_approved(self, request):
        """Whether this exact grant — scopes *and* resource — already exists."""
        client_id = request.GET.get("client_id")
        scopes = (request.GET.get("scope") or "").split()
        if not client_id:
            return False
        application = get_application_model().objects.filter(client_id=client_id).first()
        if application is None:
            return False
        for token in (
            get_access_token_model()
            .objects.filter(user=request.user, application=application, expires__gt=timezone.now())
            .iterator()
        ):
            if token.allow_scopes(scopes) and sorted(token.resource or []) == self._resources:
                return True
        return False

    def describe_resource(self, resource):
        """A human label for the parsed resource.

        The single-tenant default is the whole account. Override for team- or
        project-scoped shapes (resolve names against the *user's own* tenants so
        an unknown slug reads as itself rather than confirming a stranger exists).
        """
        return "your account"

    def _resource_label(self):
        resources = getattr(self, "_resources", [])
        if not resources:
            return ""
        if len(resources) > 1:
            return ", ".join(resources)
        parsed = self.resource_codec.parse_url(resources[0])
        if parsed is None:
            return resources[0]
        return self.describe_resource(parsed)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = context.get("application")
        client_id = context.get("client_id") or ""
        host = _client_host(client_id)

        context["client_host"] = host
        context["client_claimed_name"] = getattr(application, "name", "") or ""
        # The heading. For a CIMD client this is the one thing it cannot lie
        # about; for a registered client the name we gave it ourselves.
        context["client_display"] = host or context["client_claimed_name"]
        context["client_is_self_asserted"] = bool(host)
        context["resource_label"] = self._resource_label()

        redirect_uris = (getattr(application, "redirect_uris", "") or "").split()
        context["redirect_is_loopback"] = bool(redirect_uris) and all(
            _loopback(uri) for uri in redirect_uris
        )
        context["redirect_uri_display"] = context.get("redirect_uri") or ""

        # Fail closed when the page cannot show what it exists to show. If who is
        # asking or what they want is missing, the honest render is a refusal that
        # names the gap, not an Authorize button over blanks. ``consent_blocked``
        # drives both the template (which hides the buttons) and the 400 status.
        reasons = []
        if not context["client_display"]:
            reasons.append("it did not name the application asking")
        if not context.get("scopes"):
            reasons.append("it did not say what access it wants")
        # A connector is addressed by exactly one resource this server
        # recognises. More than one, or a foreign/unknown resource, is refused
        # here. The audience validator (RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR)
        # and DOT's grant->token narrowing (invalid_target) enforce the same
        # boundary at issuance; this makes it visible and fail-closed at consent.
        resources = getattr(self, "_resources", [])
        if len(resources) > 1:
            reasons.append("it named more than one resource")
        elif resources and self.resource_codec.parse_url(resources[0]) is None:
            reasons.append("it named a resource this server does not recognise")
        context["consent_reasons"] = reasons
        context["consent_blocked"] = bool(reasons)
        return context

    def error_response(self, error, application, **kwargs):
        # The other way this page goes blank. When the request cannot be validated
        # at all — a CIMD document DOT rejects, an unknown client, a bad resource —
        # and the error cannot bounce back to a redirect_uri, DOT renders THIS
        # template with an error-only context (no client, no scopes). That path
        # never reaches get_context_data, so intercept it and refuse explicitly.
        response = super().error_response(error, application, **kwargs)
        if getattr(response, "template_name", None) is None:
            # A redirect back to the client; it carries the error itself.
            return response
        context = {"consent_blocked": True, "consent_reasons": []}
        return self.response_class(
            request=self.request,
            template=self.get_template_names(),
            context=context,
            using=self.template_engine,
            status=400,
        )

    def render_to_response(self, context, **response_kwargs):
        # A page that had to refuse is a bad request, not a 200.
        if context.get("consent_blocked"):
            response_kwargs["status"] = 400
        return super().render_to_response(context, **response_kwargs)
