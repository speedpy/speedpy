"""Tell a person that we stopped emailing one of their addresses .

The gap this closes: when an address hard-bounces we stop sending to it, and the
only way we would normally tell somebody is by email — to the address we just
stopped using. So a real customer whose mailbox filled up, whose domain expired,
or whose provider started rejecting us goes silent and never finds out why. From
their side the product simply stopped working: no password resets, no
invitations, no notifications, and no error anywhere.

A template tag rather than a view override, because the page is allauth's own
(``account/email.html``, a ``vendor`` file). One query, only on that page.
"""

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def suppressed_addresses_for(user):
    """Suppression state for this user's own addresses.

    Returns ``{"rows": [...], "all_blocked": bool, "support_email": str}``.
    Empty rows for anonymous users.

    Matched through ``EmailAddress`` rather than ``user.email`` so a secondary
    address is covered too — a person can perfectly well have their primary
    working and an old one dead.

    ``all_blocked`` exists so the page can tell the difference between an
    annoyance and being locked out. With one address left working there is
    nothing urgent to do; with none, the person cannot receive a password reset
    and needs to add another address now. Advice that only applies in the second
    case should not be shown in the first.
    """
    support = (
        getattr(settings, "SUPPORT_EMAIL", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or "support@example.com"
    )
    empty = {"rows": [], "all_blocked": False, "support_email": support}
    if not getattr(user, "is_authenticated", False):
        return empty

    from allauth.account.models import EmailAddress

    from speedpycom.models import SuppressedEmail

    owned = {
        e.lower()
        for e in EmailAddress.objects.filter(user=user).values_list(
            "email", flat=True
        )
    }
    if not owned:
        return empty

    rows = list(
        SuppressedEmail.objects.filter(
            email__in=owned, released_at__isnull=True
        ).order_by("email")
    )
    return {
        "rows": rows,
        "all_blocked": bool(rows) and len(rows) >= len(owned),
        "support_email": support,
    }
