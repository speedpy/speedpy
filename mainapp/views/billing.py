"""Billing views — checkout, customer portal, overview, and provider webhooks.

Team mode bills the Team (owner-only); user mode (teams disabled) bills the
authenticated User. The two share the overview/checkout/portal logic via
``_BillingActionsMixin`` and only differ in how the billable account is resolved
and which template/URLs they use.

Provider webhooks are public, signature-verified, idempotent, and never raise to
the provider — handled errors return 200 (logged), unexpected errors return 500
so the provider retries (and the dedupe marker is rolled back).
"""

import re

import structlog
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from mainapp.billing import registry, state, webhooks
from mainapp.billing.base import CheckoutResult
from mainapp.models import BillingEventLog
from mainapp.subscription_plans import (
    SUBSCRIPTION_PLANS,
    get_provider_price_id,
    get_public_plans,
)
from mainapp.views.teams import TeamOwnerRequiredMixin, TeamViewMixin

logger = structlog.get_logger(__name__)


class _BillingActionsMixin:
    """Shared overview/checkout/portal logic.

    Subclasses must provide ``self.billable`` and the URL helpers below.
    """

    # Overridden per mode.
    overview_url_name = None  # e.g. "team_billing" / "account_billing"

    def _overview_url(self):
        raise NotImplementedError

    def _checkout_url(self, plan_key, interval):
        raise NotImplementedError

    def _portal_url(self):
        raise NotImplementedError

    def _activation_url(self):
        raise NotImplementedError

    def _checkout_success_url(self):
        return self.request.build_absolute_uri(self._overview_url())

    def _checkout_cancel_url(self):
        return self.request.build_absolute_uri(self._overview_url())

    # -- Post-checkout activation ----------------------------------------

    #: Provider transaction ids are opaque strings; validate the shape before
    #: putting one in an API path. Fail closed on anything else.
    TRANSACTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}$")

    def activation_status(self):
        """Snapshot the success page polls until the paid plan appears."""
        billable = self.billable
        cfg = state.get_plan_config_for(billable)
        return {
            "plan_key": state.effective_plan_key(billable),
            "plan_name": cfg.get("name", "") or "",
            "is_paid": bool(cfg.get("is_paid")),
            "billing_state": state.get_billing_state(billable),
            "has_active_subscription": state.has_active_ish_subscription(billable),
        }

    def reconcile_transaction(self, transaction_id):
        """Provision from live provider state instead of waiting for the webhook.

        Returns ``(payload, status_code)``. Every failure path returns the current
        activation status with ``reconciled: False`` rather than an error, so the
        page falls back to polling for the webhook instead of showing a dead end —
        except a cross-tenant attempt, which is a 404.
        """
        payload = {"reconciled": False}

        if not transaction_id or not self.TRANSACTION_ID_RE.match(transaction_id):
            payload.update(self.activation_status())
            return payload, 400

        try:
            adapter = registry.get_adapter()
        except ImproperlyConfigured as exc:
            logger.error("billing_not_configured", error=str(exc))
            payload.update(self.activation_status())
            return payload, 200

        normalized = adapter.fetch_subscription_state(transaction_id)
        if not normalized:
            # Provider could not tell us yet (or does not support the read).
            # The webhook remains the path; the caller polls.
            payload.update(self.activation_status())
            return payload, 200

        # Tenant guard (spec §2.0 in spirit): the account is resolved from the
        # provider's signed custom data, so a member of team A must not be able to
        # drive provisioning by posting a transaction id belonging to team B.
        # Check BEFORE applying, never after — applying first would be the bug.
        our_type, our_id = state.billable_token(self.billable)
        if (
            normalized.get("billable_type") != our_type
            or str(normalized.get("billable_id")) != str(our_id)
        ):
            logger.warning(
                "billing_reconcile_tenant_mismatch",
                provider=getattr(adapter, "provider", ""),
                expected_billable_id=str(our_id),
            )
            raise Http404("Unknown transaction")

        webhooks.apply_subscription_update(adapter.provider, normalized)
        # apply_subscription_update writes the plan through its OWN freshly loaded
        # billable, so the instance this request is holding (loaded during
        # dispatch) is now stale and would report the pre-checkout plan back to
        # the browser — which is the exact bug this endpoint exists to prevent.
        refresh = getattr(self.billable, "refresh_from_db", None)
        if callable(refresh):
            refresh()
        status = self.activation_status()
        payload.update(status)
        payload["reconciled"] = bool(status["has_active_subscription"])
        logger.info(
            "billing_reconciled_from_transaction",
            provider=adapter.provider,
            reconciled=payload["reconciled"],
            plan_key=status["plan_key"],
        )
        return payload, 200

    def get_billing_context(self):
        billable = self.billable
        current_plan_key = state.effective_plan_key(billable)
        plan_rows = []
        for cfg in get_public_plans():
            row = {"plan": cfg, "is_current": cfg["key"] == current_plan_key}
            if cfg.get("is_paid") and not cfg.get("is_contact"):
                row["checkout_monthly_url"] = self._checkout_url(cfg["key"], "monthly")
                row["checkout_yearly_url"] = self._checkout_url(cfg["key"], "yearly")
            plan_rows.append(row)
        return {
            "plan_rows": plan_rows,
            "current_plan_key": current_plan_key,
            "current_plan": state.get_plan_config_for(billable),
            "subscription": state.get_current_subscription(billable),
            "billing_state": state.get_billing_state(billable),
            "has_active_subscription": state.has_active_ish_subscription(billable),
            "over_limit": state.over_limit_report(billable),
            "billing_provider": getattr(settings, "SPEEDPY_BILLING_PROVIDER", ""),
            "portal_url": self._portal_url(),
            # Both the notice and the reason the buttons are gone.
            "deletion_scheduled": getattr(
                self.billable, "is_deletion_scheduled", False
            ),
            "deletion_scheduled_at": getattr(
                self.billable, "deletion_scheduled_at", None
            ),
            "overview_url": self._overview_url(),
            "activation_url": self._activation_url(),
            # Rendered server-side so the pending notice appears on first paint
            # rather than flashing in from JS. Suppressed the moment the
            # subscription really is active, so a stale bookmark of
            # ?activating=1 can never claim a paid plan is still pending.
            "activating": (
                self.request.GET.get("activating") == "1"
                and not state.has_active_ish_subscription(billable)
            ),
        }

    #: Shown when the billable is on its way out.
    DELETION_SCHEDULED_MESSAGE = (
        "This team is scheduled for deletion, so its billing is closed. Undo the "
        "deletion first if you want to keep it."
    )

    def _refuse_if_deletion_scheduled(self, request):
        """Close every billing door while a deletion is pending, or None.

        Both doors, not just checkout. A provider's own portal can start a new
        subscription or resume a paused one, and a subscription that appears
        while the deletion is running is the one case the purge cannot finish
        cleanly — by then the team's stored objects are already gone. Shutting
        the doors is what makes that race rare enough to accept.
        """
        if not getattr(self.billable, "is_deletion_scheduled", False):
            return None
        messages.error(request, self.DELETION_SCHEDULED_MESSAGE)
        return redirect(self._overview_url())

    def start_checkout(self, request, plan_key, interval):
        """Validate and start checkout; returns an HttpResponse."""
        plan = SUBSCRIPTION_PLANS.get(plan_key)
        if not plan or not plan.get("is_paid") or plan.get("is_contact"):
            raise Http404("Unknown plan")
        if interval not in ("monthly", "yearly"):
            raise Http404("Unknown billing interval")

        # A team on its way out must not be given a subscription: the deletion
        # is refused while one is live, so the person would end up paying for a
        # team they had already asked us to delete.
        refusal = self._refuse_if_deletion_scheduled(request)
        if refusal:
            return refusal

        # Plan changes go through the customer portal, not a second checkout.
        if state.has_active_ish_subscription(self.billable):
            messages.info(
                request,
                "You already have an active subscription. Use the billing portal "
                "to change your plan.",
            )
            return redirect(self._overview_url())

        provider = getattr(settings, "SPEEDPY_BILLING_PROVIDER", "")
        price_id = get_provider_price_id(provider, plan_key, interval)
        if not price_id:
            messages.error(
                request,
                "This plan isn't available for checkout yet. Please try again later.",
            )
            logger.error(
                "billing_missing_price_id",
                provider=provider,
                plan_key=plan_key,
                interval=interval,
            )
            return redirect(self._overview_url())

        try:
            adapter = registry.get_adapter()
        except ImproperlyConfigured as exc:
            messages.error(request, "Billing is not configured. Please contact support.")
            logger.error("billing_not_configured", error=str(exc))
            return redirect(self._overview_url())

        billable_type, billable_id = state.billable_token(self.billable)
        result = adapter.create_checkout(
            billable=self.billable,
            billable_type=billable_type,
            billable_id=billable_id,
            plan_key=plan_key,
            interval=interval,
            price_id=price_id,
            customer_email=request.user.email,
            success_url=self._checkout_success_url(),
            cancel_url=self._checkout_cancel_url(),
        )

        if result.mode == CheckoutResult.MODE_REDIRECT:
            if not result.url:
                messages.error(request, "Could not start checkout. Please try again.")
                return redirect(self._overview_url())
            return HttpResponseRedirect(result.url)

        # Client-side checkout (Paddle): render the overlay template.
        context = self.get_context_data() if hasattr(self, "get_context_data") else {}
        context.update(result.context)
        context.update(
            {
                "plan": plan,
                "interval": interval,
                # Lets the overlay provision from checkout.completed instead of
                # racing the webhook, then land on an already-correct page.
                "activation_url": self._activation_url(),
                "overview_url": self._overview_url(),
            }
        )
        from django.shortcuts import render

        return render(request, "mainapp/billing/checkout.html", context)

    def open_portal(self, request):
        # The portal is a second door to the same place: both Stripe's and
        # Paddle's let somebody start or resume a subscription from outside our
        # UI, and we would only learn about it from a webhook.
        refusal = self._refuse_if_deletion_scheduled(request)
        if refusal:
            return refusal

        sub = state.get_current_subscription(self.billable)
        if not sub or not sub.provider_customer_id:
            messages.error(request, "No subscription found to manage.")
            return redirect(self._overview_url())
        try:
            adapter = registry.get_adapter_for_provider(sub.provider)
        except ImproperlyConfigured:
            messages.error(request, "Billing is not configured. Please contact support.")
            return redirect(self._overview_url())
        url = adapter.create_portal_session(
            customer_id=sub.provider_customer_id,
            return_url=self.request.build_absolute_uri(self._overview_url()),
        )
        if not url:
            messages.error(
                request, "Could not open the billing portal right now. Please try again."
            )
            return redirect(self._overview_url())
        return HttpResponseRedirect(url)


# --------------------------------------------------------------------------
# Team mode (SPEEDPY_TEAMS_ENABLED)
# --------------------------------------------------------------------------
class _TeamBillingURLsMixin:
    @property
    def billable(self):
        return self.team

    def _overview_url(self):
        return reverse("team_billing", kwargs={"team_id": self.team.pk})

    def _checkout_url(self, plan_key, interval):
        return reverse(
            "team_billing_checkout",
            kwargs={"team_id": self.team.pk, "plan_key": plan_key, "interval": interval},
        )

    def _portal_url(self):
        return reverse("team_billing_portal", kwargs={"team_id": self.team.pk})

    def _activation_url(self):
        return reverse("team_billing_activation", kwargs={"team_id": self.team.pk})


class TeamBillingView(
    TeamOwnerRequiredMixin, _TeamBillingURLsMixin, _BillingActionsMixin, TemplateView
):
    template_name = "mainapp/billing/team_billing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_billing_context())
        return context


class TeamCheckoutView(
    TeamOwnerRequiredMixin, _TeamBillingURLsMixin, _BillingActionsMixin, TemplateView
):
    template_name = "mainapp/billing/checkout.html"

    def get(self, request, *args, **kwargs):
        return self.start_checkout(request, kwargs.get("plan_key"), kwargs.get("interval"))


class TeamBillingPortalView(
    TeamOwnerRequiredMixin, _TeamBillingURLsMixin, _BillingActionsMixin, View
):
    def post(self, request, *args, **kwargs):
        return self.open_portal(request)


class _ActivationJSONMixin:
    """JSON endpoints the post-checkout page uses to avoid showing a stale plan.

    ``GET`` polls the current activation status; ``POST`` additionally reconciles
    from the provider before answering.
    """

    def get(self, request, *args, **kwargs):
        return JsonResponse(self.activation_status())

    def post(self, request, *args, **kwargs):
        transaction_id = (request.POST.get("transaction_id") or "").strip()
        payload, status_code = self.reconcile_transaction(transaction_id)
        return JsonResponse(payload, status=status_code)


class TeamBillingActivationView(
    TeamOwnerRequiredMixin, _TeamBillingURLsMixin, _BillingActionsMixin,
    _ActivationJSONMixin, View
):
    pass


# --------------------------------------------------------------------------
# User mode (teams disabled)
# --------------------------------------------------------------------------
class _AccountBillingBase(LoginRequiredMixin, _BillingActionsMixin):
    """Base for account billing views; rejects access when teams are enabled."""

    def dispatch(self, request, *args, **kwargs):
        if getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
            raise Http404("Account billing is only available when teams are disabled.")
        return super().dispatch(request, *args, **kwargs)

    @property
    def billable(self):
        return self.request.user

    def _overview_url(self):
        return reverse("account_billing")

    def _checkout_url(self, plan_key, interval):
        return reverse(
            "account_billing_checkout",
            kwargs={"plan_key": plan_key, "interval": interval},
        )

    def _portal_url(self):
        return reverse("account_billing_portal")

    def _activation_url(self):
        return reverse("account_billing_activation")


class AccountBillingView(_AccountBillingBase, TemplateView):
    template_name = "mainapp/billing/account_billing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_billing_context())
        return context


class AccountCheckoutView(_AccountBillingBase, TemplateView):
    template_name = "mainapp/billing/checkout.html"

    def get(self, request, *args, **kwargs):
        return self.start_checkout(request, kwargs.get("plan_key"), kwargs.get("interval"))


class AccountBillingActivationView(_AccountBillingBase, _ActivationJSONMixin, View):
    pass


class AccountBillingPortalView(_AccountBillingBase, View):
    def post(self, request, *args, **kwargs):
        return self.open_portal(request)


# --------------------------------------------------------------------------
# Provider webhooks (public, signature-verified, idempotent)
# --------------------------------------------------------------------------
class _ProviderWebhookView(View):
    provider = ""

    def post(self, request, *args, **kwargs):
        try:
            adapter = registry.get_adapter_for_provider(self.provider)
        except ImproperlyConfigured:
            return HttpResponse(status=503)

        event = adapter.verify_and_parse_webhook(request)
        if event is None:
            logger.warning("billing_webhook_invalid", provider=self.provider)
            return HttpResponse(status=403)

        event_id = adapter.get_event_id(event)
        if webhooks.already_processed(self.provider, event_id):
            return HttpResponse(status=200)

        try:
            adapter.process_event(event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "billing_webhook_processing_error",
                provider=self.provider,
                event_type=adapter.get_event_type(event),
                error=str(exc),
                exc_info=True,
            )
            # Roll back the dedupe marker so the provider's retry reprocesses.
            if event_id:
                BillingEventLog.objects.filter(
                    provider=self.provider, event_id=event_id
                ).delete()
            return HttpResponse(status=500)

        webhooks.record_event_meta(
            self.provider, event_id, adapter.get_event_type(event), event if isinstance(event, dict) else {}
        )
        return HttpResponse(status=200)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(_ProviderWebhookView):
    provider = "stripe"


@method_decorator(csrf_exempt, name="dispatch")
class PaddleWebhookView(_ProviderWebhookView):
    provider = "paddle"
