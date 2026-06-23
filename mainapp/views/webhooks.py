import secrets
import time
import uuid

import structlog
from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from mainapp.forms.webhooks import WebhookEndpointForm
from mainapp.models.webhooks import WebhookDelivery, WebhookEndpoint
from mainapp.views.teams import TeamViewMixin
from mainapp.webhooks.events import WebhookEvent
from usermodel.views import _encrypt_token, _decrypt_token

logger = structlog.get_logger(__name__)


class WebhookWriteMixin(TeamViewMixin):
    """Mixin that allows owner/admin/member but denies viewer.

    Checks the role BEFORE the view handler runs so that mutations
    cannot execute before the permission gate.
    """

    def dispatch(self, request, *args, **kwargs):
        if not getattr(django_settings, "SPEEDPY_TEAMS_ENABLED", True):
            raise Http404("Teams functionality is disabled")
        team = self._get_team(kwargs)
        team_membership = self._get_membership(request.user, team)
        self.team = team
        self.team_membership = team_membership
        if team_membership.role not in ("owner", "admin", "member"):
            raise PermissionDenied("Your role does not allow managing webhooks.")
        # Skip TeamViewMixin.dispatch (already resolved) and go to
        # LoginRequiredMixin -> View.dispatch which runs the handler.
        return super(TeamViewMixin, self).dispatch(request, *args, **kwargs)


class TeamWebhookListView(TeamViewMixin, ListView):
    """List webhook endpoints for a team."""

    template_name = "mainapp/webhooks/list.html"
    context_object_name = "endpoints"

    def get_queryset(self):
        return WebhookEndpoint.objects.filter(team=self.team).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        encrypted_secret = self.request.session.pop("new_webhook_encrypted_secret", None)
        context["new_secret"] = _decrypt_token(encrypted_secret) if encrypted_secret else None
        context["new_webhook_name"] = self.request.session.pop("new_webhook_name", None)
        context["can_manage"] = self.team_membership.role in ("owner", "admin", "member")
        return context


class TeamWebhookCreateView(WebhookWriteMixin, FormView):
    """Create a new webhook endpoint."""

    template_name = "mainapp/webhooks/create.html"
    form_class = WebhookEndpointForm

    def form_valid(self, form):
        endpoint = WebhookEndpoint(
            team=self.team,
            name=form.cleaned_data.get("name", ""),
            url=form.cleaned_data["url"],
            events=form.cleaned_data["events"],
        )
        endpoint.save()

        self.request.session["new_webhook_encrypted_secret"] = _encrypt_token(endpoint.secret)
        self.request.session["new_webhook_name"] = endpoint.name or endpoint.url

        logger.info(
            "webhook_endpoint_created",
            user_id=str(self.request.user.id),
            team_id=str(self.team.id),
            endpoint_id=str(endpoint.id),
        )
        messages.success(
            self.request,
            f'Webhook created. Copy the signing secret now \u2014 it won\'t be shown again.',
        )
        return redirect(reverse("team_webhooks", kwargs={"team_id": self.team.pk}))


class TeamWebhookDetailView(TeamViewMixin, DetailView):
    """Show webhook details and recent deliveries."""

    template_name = "mainapp/webhooks/detail.html"
    context_object_name = "endpoint"

    def get_object(self, queryset=None):
        return get_object_or_404(
            WebhookEndpoint,
            id=self.kwargs["webhook_id"],
            team=self.team,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["deliveries"] = (
            WebhookDelivery.objects.filter(endpoint=self.object)
            .order_by("-created_at")[:20]
        )
        context["can_manage"] = self.team_membership.role in ("owner", "admin", "member")
        encrypted_secret = self.request.session.pop("rotated_webhook_encrypted_secret", None)
        context["new_secret"] = _decrypt_token(encrypted_secret) if encrypted_secret else None
        return context


class TeamWebhookRevokeView(WebhookWriteMixin, View):
    """Revoke (deactivate) a webhook endpoint."""

    def post(self, request, *args, **kwargs):
        endpoint = get_object_or_404(
            WebhookEndpoint,
            id=self.kwargs["webhook_id"],
            team=self.team,
        )
        endpoint.is_active = False
        endpoint.events = []
        endpoint.save(update_fields=["is_active", "events", "updated_at"])

        logger.info(
            "webhook_endpoint_revoked",
            user_id=str(request.user.id),
            team_id=str(self.team.id),
            endpoint_id=str(endpoint.id),
        )
        messages.success(request, f'Webhook "{endpoint.name or endpoint.url}" has been revoked.')
        return redirect(reverse("team_webhooks", kwargs={"team_id": self.team.pk}))


class TeamWebhookTestView(WebhookWriteMixin, View):
    """Send a test delivery to a webhook endpoint."""

    def post(self, request, *args, **kwargs):
        endpoint = get_object_or_404(
            WebhookEndpoint,
            id=self.kwargs["webhook_id"],
            team=self.team,
        )

        if not endpoint.is_active:
            messages.error(request, "Cannot send test delivery to an inactive endpoint.")
            return redirect(
                reverse("team_webhook_detail", kwargs={
                    "team_id": self.team.pk,
                    "webhook_id": endpoint.pk,
                })
            )

        event_type = endpoint.events[0] if endpoint.events and endpoint.events[0] != "*" else "team.member.added"

        from mainapp.tasks.webhooks import deliver_webhook

        event_id = f"evt_{uuid.uuid4().hex}"
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": int(time.time()),
            "api_version": "2026-06-01",
            "data": {
                "test": True,
                "endpoint_id": str(endpoint.id),
                "triggered_by": str(request.user.id),
            },
        }

        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        transaction.on_commit(lambda pk=delivery.pk: deliver_webhook.delay(pk))

        logger.info(
            "webhook_test_delivery_created",
            user_id=str(request.user.id),
            team_id=str(self.team.id),
            endpoint_id=str(endpoint.id),
            delivery_id=delivery.pk,
        )
        messages.success(request, "Test delivery dispatched.")
        return redirect(
            reverse("team_webhook_detail", kwargs={
                "team_id": self.team.pk,
                "webhook_id": endpoint.pk,
            })
        )


class TeamWebhookRotateSecretView(WebhookWriteMixin, View):
    """Rotate the signing secret for a webhook endpoint."""

    def post(self, request, *args, **kwargs):
        endpoint = get_object_or_404(
            WebhookEndpoint,
            id=self.kwargs["webhook_id"],
            team=self.team,
        )
        endpoint.secret = secrets.token_urlsafe(32)
        endpoint.save(update_fields=["secret", "updated_at"])

        self.request.session["rotated_webhook_encrypted_secret"] = _encrypt_token(endpoint.secret)

        logger.info(
            "webhook_endpoint_secret_rotated",
            user_id=str(request.user.id),
            team_id=str(self.team.id),
            endpoint_id=str(endpoint.id),
        )
        messages.success(request, "Signing secret rotated. Copy it now \u2014 it won't be shown again.")
        return redirect(
            reverse("team_webhook_detail", kwargs={
                "team_id": self.team.pk,
                "webhook_id": endpoint.pk,
            })
        )
