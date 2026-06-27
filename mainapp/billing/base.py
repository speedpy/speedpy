"""Common billing adapter interface.

Provider adapters (Stripe, Paddle) implement this interface so application code
(views, webhooks, catalog commands) is provider-agnostic. Each adapter keeps the
provider's API, signature scheme, and payload shapes as private implementation
details.
"""

from abc import ABC, abstractmethod


class CheckoutResult:
    """The result of starting a checkout.

    Providers differ in how checkout is launched:

    - ``mode="redirect"`` — a server-created hosted checkout (Stripe Checkout
      Session). The view should redirect the browser to ``url``.
    - ``mode="client"`` — a client-side overlay (Paddle.js). The view should
      render a template using ``context`` (price id, client token, custom data).
    """

    MODE_REDIRECT = "redirect"
    MODE_CLIENT = "client"

    def __init__(self, mode, url=None, context=None):
        self.mode = mode
        self.url = url
        self.context = context or {}


class BillingAdapter(ABC):
    """Provider-neutral billing operations."""

    #: Provider key, e.g. "stripe" / "paddle".
    provider = ""

    @classmethod
    @abstractmethod
    def is_configured(cls):
        """Whether the adapter has the credentials it needs to operate."""

    @abstractmethod
    def create_checkout(
        self,
        *,
        billable,
        billable_type,
        billable_id,
        plan_key,
        interval,
        price_id,
        customer_email,
        success_url,
        cancel_url,
    ):
        """Start a checkout for the given plan/interval.

        Must embed ``billable_type``, ``billable_id``, ``plan_key`` and
        ``interval`` in provider metadata / custom data so the webhook can
        resolve the account without trusting the customer email.

        Returns a :class:`CheckoutResult`.
        """

    @abstractmethod
    def create_portal_session(self, *, customer_id, return_url):
        """Create a customer/billing portal session, returning its URL or None."""

    @abstractmethod
    def verify_and_parse_webhook(self, request):
        """Verify the request signature and return the parsed event dict.

        Returns ``None`` when the signature is missing/invalid or the body is
        unparseable (the view turns that into a 4xx).
        """

    @abstractmethod
    def get_event_id(self, event):
        """Return a stable provider event id used for idempotent dedupe."""

    @abstractmethod
    def get_event_type(self, event):
        """Return the provider event type string (for logging/audit)."""

    @abstractmethod
    def process_event(self, event):
        """Apply a verified webhook event to local billing state (idempotent)."""
