"""Is this address worth sending to? (spec §3.19)

One validator, called from every place an email address enters the system:
signup, team invitations, public forms, CSV imports. Before this, the check
lived inline in ``usermodel/forms.py`` and therefore covered signup and nothing
else — which is a strange place to draw the line, because signup was never the
only door.

**Why bother at all.** A bounce is not free. Amazon SES tracks a bounce rate per
account and suspends sending above roughly 5%, so a handful of undeliverable
addresses collected through a public form can cost the ability to send any mail
at all. Refusing the address while the person is still looking at the form is
the cheapest possible moment to catch a typo.

**What it does and does not catch.** A missing MX record is a hard rejection.
A *typo with a valid MX* is not caught and cannot be — ``gmail.co`` resolves
perfectly well. Suggesting a correction for near-misses is a separate idea, not
this.

Three deliberate choices, each of which was a defect in the inline version:

``cached per domain``
    A DNS lookup per submission is fine; a DNS lookup per CSV row is not. Cached
    on the DOMAIN, so an import of five thousand gmail addresses costs one
    lookup. Positive answers are cached for a day, negative ones for an hour —
    a domain that has just fixed its DNS should not stay refused all day.

``fails OPEN on a non-answer``
    A timeout, a SERVFAIL, an unreachable resolver: we did not learn anything,
    so we do not refuse anybody. ``NXDOMAIN`` and ``NoAnswer`` are different —
    those are answers, and they say no.

``MX-only by default``
    RFC 5321's implicit-MX rule says a domain with only an A record IS
    deliverable, so strict MX-only rejects a few technically-valid domains.
    That is accepted on purpose (Kostja, 2026-08-21): a bounce costs SES
    reputation and eventually the account, while the cost of the strict default
    is a rare support message. ``EMAIL_MX_ALLOW_IMPLICIT_MX`` turns the fallback
    on for boilerplate users who would rather not refuse them.

The blocklists (``email_domains``) are checked first, because they are two set
lookups against data already in memory and there is no reason to pay for DNS to
reject mailinator.com.
"""

import dataclasses

import structlog
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from speedpycom.services.email_domains import (
    BLOCKED_EMAIL_MESSAGE,
    domain_of,
    is_blocked,
)

logger = structlog.get_logger(__name__)

#: Deliverable as far as we can tell.
OUTCOME_OK = "ok"
#: On a blocklist — throwaway provider, or this project's own list.
OUTCOME_BLOCKED = "blocked"
#: The domain answered, and the answer was "no mail here".
OUTCOME_NO_MX = "no_mx"
#: Not an address we can even find a domain in.
OUTCOME_MALFORMED = "malformed"
#: We did not learn anything — timeout, SERVFAIL, no resolver. Fails open.
OUTCOME_UNKNOWN = "unknown"
#: Checking is switched off.
OUTCOME_DISABLED = "disabled"

#: Said to somebody who has probably mistyped their own address. Deliberately
#: different from BLOCKED_EMAIL_MESSAGE: this one is actionable ("check for
#: typos"), where a blocklist refusal must not hint at why.
NO_MX_MESSAGE = _(
    "This email domain does not appear to accept mail. Please check it for typos."
)

CACHE_PREFIX = "speedpy:mx:"


@dataclasses.dataclass(frozen=True)
class EmailVerdict:
    outcome: str
    domain: str = ""

    @property
    def rejects(self):
        return self.outcome in (OUTCOME_BLOCKED, OUTCOME_NO_MX, OUTCOME_MALFORMED)

    @property
    def message(self):
        """What to show the person. Empty when nothing is wrong."""
        if self.outcome == OUTCOME_BLOCKED:
            return BLOCKED_EMAIL_MESSAGE
        if self.outcome in (OUTCOME_NO_MX, OUTCOME_MALFORMED):
            return NO_MX_MESSAGE
        return ""


def enabled():
    """Master switch. Defaults to on outside DEBUG.

    Also honours the older ``SIGNUP_EMAIL_MX_CHECK`` so a project that turned the
    inline check off does not silently get it back when it pulls this in.
    """
    if not getattr(settings, "SIGNUP_EMAIL_MX_CHECK", True):
        return False
    return bool(
        getattr(settings, "EMAIL_DELIVERABILITY_CHECK", not settings.DEBUG)
    )


def timeout_seconds():
    """Shorter than the inline version's 5s. This now runs on public forms, and
    five seconds of a worker per submission is a denial-of-service assist."""
    return float(getattr(settings, "EMAIL_MX_TIMEOUT_SECONDS", 2.0))


def check(email):
    """Classify one address. Never raises, never blocks for long.

    A blank address is ``OK``: whether the field is required is the caller's
    business, and answering "malformed" for an empty optional field would make
    every caller special-case it.
    """
    email = (email or "").strip()
    if not email:
        return EmailVerdict(outcome=OUTCOME_OK)

    # No "@" at all is not an address, and asking DNS about it would spend two
    # seconds of a public request to learn nothing. (email_domains' parser
    # deliberately passes a bare domain through, because `is_blocked("x.com")`
    # has to work — so the check belongs here, not there.)
    if "@" not in email:
        return EmailVerdict(outcome=OUTCOME_MALFORMED)

    domain = domain_of(email)
    if not domain:
        return EmailVerdict(outcome=OUTCOME_MALFORMED)

    # Cheap, in-memory, and the answer we most want to give. Runs even when the
    # DNS half is switched off: a blocklist is a policy, not a probe.
    if is_blocked(email):
        return EmailVerdict(outcome=OUTCOME_BLOCKED, domain=domain)

    if not enabled():
        return EmailVerdict(outcome=OUTCOME_DISABLED, domain=domain)

    cached = _cached(domain)
    if cached is not None:
        return EmailVerdict(outcome=cached, domain=domain)

    outcome = _resolve(domain)
    # Only real answers are cached. Caching a timeout would turn one bad minute
    # into an hour of it.
    if outcome in (OUTCOME_OK, OUTCOME_NO_MX):
        _store(domain, outcome)
    return EmailVerdict(outcome=outcome, domain=domain)


def validate(email):
    """``check``, as a Django validator. Raises ``ValidationError``.

    For form fields and DRF serializers, which both understand that exception.
    """
    from django.core.exceptions import ValidationError

    verdict = check(email)
    if verdict.rejects:
        raise ValidationError(verdict.message)
    return email


def _cached(domain):
    try:
        return cache.get(f"{CACHE_PREFIX}{domain}")
    except Exception:
        logger.exception("email_mx_cache_error", domain=domain)
        return None


def _store(domain, outcome):
    ttl = (
        int(getattr(settings, "EMAIL_MX_CACHE_SECONDS", 86400))
        if outcome == OUTCOME_OK
        # Shorter, so a domain that has just fixed its DNS is not refused all
        # day. The asymmetry is the point.
        else int(getattr(settings, "EMAIL_MX_NEGATIVE_CACHE_SECONDS", 3600))
    )
    try:
        cache.set(f"{CACHE_PREFIX}{domain}", outcome, ttl)
    except Exception:
        logger.exception("email_mx_cache_error", domain=domain)


def _resolve(domain):
    """One DNS question, or two when the implicit-MX fallback is on."""
    import dns.exception
    import dns.resolver

    lifetime = timeout_seconds()
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=lifetime)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # An answer, and the answer is no.
        return _implicit_mx(domain, lifetime)
    except dns.resolver.NoNameservers:
        # Every nameserver refused or SERVFAIL'd. Not the same as "no record" —
        # a broken zone should not cost us a real customer, so fail open.
        logger.info("email_mx_no_nameservers", domain=domain)
        return OUTCOME_UNKNOWN
    except dns.exception.DNSException as exc:
        logger.info(
            "email_mx_unresolved", domain=domain, error=type(exc).__name__
        )
        return OUTCOME_UNKNOWN
    except Exception:
        # Never let a resolver surprise become a 500 on a public form.
        logger.exception("email_mx_error", domain=domain)
        return OUTCOME_UNKNOWN

    # An MX set that is empty, or is a single "." (RFC 7505's explicit "this
    # domain sends and receives no mail"), is a no.
    hosts = [str(getattr(r, "exchange", "")).strip() for r in answers]
    hosts = [h for h in hosts if h and h != "."]
    if not hosts:
        return _implicit_mx(domain, lifetime)
    return OUTCOME_OK


def _implicit_mx(domain, lifetime):
    """RFC 5321: with no MX, the A/AAAA record is the mail exchanger.

    Off by default — see the module docstring. Strictness here is a decision
    about SES reputation, not about correctness.
    """
    if not getattr(settings, "EMAIL_MX_ALLOW_IMPLICIT_MX", False):
        return OUTCOME_NO_MX

    import dns.exception
    import dns.resolver

    for rdtype in ("A", "AAAA"):
        try:
            if list(dns.resolver.resolve(domain, rdtype, lifetime=lifetime)):
                return OUTCOME_OK
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue
        except dns.exception.DNSException:
            return OUTCOME_UNKNOWN
        except Exception:
            logger.exception("email_mx_error", domain=domain)
            return OUTCOME_UNKNOWN
    return OUTCOME_NO_MX
