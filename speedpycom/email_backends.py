"""Email backend that refuses to send to suppressed addresses.

**Provider-agnostic.** This half of bounce handling works with any ESP, because
it wraps whatever ``EMAIL_PROVIDER`` resolves to and only consults the
suppression list. Only the *detection* half (``speedpycom/services/sns.py``) is
Amazon-specific.

The single choke point. Everything the application sends goes through
post_office, and post_office delegates to one backend, so filtering here catches
allauth's confirmation and reset mail, team invitations, billing notices and
survey invitations alike — without touching any of their call sites, several of
which live in `vendor` files.

Why a wrapper rather than a subclass of a specific backend: the real backend is
chosen at runtime by ``EMAIL_PROVIDER`` (console in development, SES in
production). This wraps whatever that resolves to, so the guard is identical in
every environment and is exercised by the test suite rather than only in
production.

**This is the thing that stops a bounce loop.** SES throttles and eventually
freezes an account that keeps hard-bouncing, so a message to a known-bad address
must not be attempted at all — not attempted-and-failed.
"""

import structlog
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.utils.module_loading import import_string

logger = structlog.get_logger(__name__)


class SuppressionAwareEmailBackend(BaseEmailBackend):
    """Drops suppressed recipients, then delegates to the configured backend."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self._inner = import_string(self._inner_path())(
            fail_silently=fail_silently, **kwargs
        )

    @staticmethod
    def _inner_path():
        from project.email_providers import resolve_email_backend

        return resolve_email_backend(getattr(settings, "EMAIL_PROVIDER", "console"))

    def open(self):
        return self._inner.open()

    def close(self):
        return self._inner.close()

    def send_messages(self, email_messages):
        from speedpycom.services.email_events import suppressed_among

        if not email_messages:
            return 0

        # One query for every recipient across the batch, rather than one per
        # message — post_office can hand us a batch.
        every_recipient = []
        for message in email_messages:
            every_recipient.extend(self._all_recipients(message))
        blocked = suppressed_among(every_recipient)

        if not blocked:
            return self._inner.send_messages(email_messages)

        sendable = []
        for message in email_messages:
            kept = self._strip(message, blocked)
            if kept:
                sendable.append(message)

        if not sendable:
            # Return 0 — the true number sent. An earlier version returned
            # len(email_messages) to stop post_office retrying, which was based
            # on a wrong reading of post_office: `Email.dispatch` calls
            # `email_message().send()` and IGNORES the returned count, marking
            # the row sent unless an exception is raised. So the lie bought
            # nothing and misreported delivery to any direct caller of
            # send_mail(), which does return the count.
            logger.warning(
                "email_send_fully_suppressed", messages=len(email_messages)
            )
            return 0
        return self._inner.send_messages(sendable)

    @staticmethod
    def _all_recipients(message):
        return [
            *(getattr(message, "to", None) or []),
            *(getattr(message, "cc", None) or []),
            *(getattr(message, "bcc", None) or []),
        ]

    def _strip(self, message, blocked):
        """Remove blocked addresses from a message; return whether any remain."""
        removed = []
        for field in ("to", "cc", "bcc"):
            addresses = getattr(message, field, None) or []
            if not addresses:
                continue
            kept = [a for a in addresses if a.strip().lower() not in blocked]
            if len(kept) != len(addresses):
                removed.extend(a for a in addresses if a not in kept)
                setattr(message, field, kept)
        if removed:
            logger.warning(
                "email_recipients_suppressed",
                removed=len(removed),
                subject=(getattr(message, "subject", "") or "")[:80],
            )
        return bool(self._all_recipients(message))
