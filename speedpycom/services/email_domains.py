"""Blocking email addresses by domain.

Two lists, deliberately separate:

``speedpycom/data/disposable_email_blocklist.conf``
    Throwaway-mail providers. Bundled, and **replaced wholesale** when it is
    refreshed from upstream — see ``speedpycom/data/README.md``.

``blocked_email_domains.txt`` (project root, path configurable)
    Yours. Domains this particular product does not want, for whatever reason.
    Kept apart from the bundled list precisely because that one gets overwritten.

Both are read once and cached in memory for the life of the process. They are
static files; re-reading 8,000 lines on every signup would be waste, and a
deploy is the natural moment for a change to take effect.

**What a refused person is told matters.** The message is deliberately vague and
identical whichever list matched. Saying "disposable addresses are not accepted"
tells somebody probing the filter exactly what to try next, and saying "this
domain is blocked" leaks a policy decision that is nobody's business. The cost is
that a real customer gets a wall, which is why the message names a support
address.
"""

import functools
import pathlib
from email.utils import parseaddr

import structlog
from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

logger = structlog.get_logger(__name__)

#: Shipped with the boilerplate. Never edit to add your own domains.
BUNDLED_LIST = pathlib.Path(__file__).resolve().parent.parent / "data" / "disposable_email_blocklist.conf"

#: One message for every reason we refuse an address, on purpose. A different
#: wording per reason IS the diagnosis, and the diagnosis is what we are not
#: disclosing.
BLOCKED_EMAIL_MESSAGE = _(
    "We cannot accept this email address. Please use a different one, or "
    "contact support if you think this is a mistake."
)


def _canonical(domain):
    """One spelling per domain, so two spellings cannot disagree.

    Lowercased, trailing root dot removed, and converted to IDNA/punycode. That
    last step matters: the bundled list contains punycode entries (`xn--...`),
    and Django converts a Unicode domain to punycode on its way out. Comparing
    the two forms literally would let `user@bücher.example` past a list holding
    `xn--bcher-kva.example` — and it would then be delivered.

    Anything IDNA refuses (an over-long label, an empty one) falls back to the
    lowercased text. A domain that cannot be encoded cannot be delivered to
    either, so the fallback only has to be consistent, not correct.
    """
    value = (domain or "").strip().lower().rstrip(".")
    if not value or value.isascii():
        return value
    try:
        return value.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return value


def _parse(text):
    """Split a blocklist into exact entries and subtree entries.

    Two sets rather than one so a miss costs a handful of set lookups instead of
    a scan. With 8,335 bundled domains the old single-set version walked every
    entry on every miss looking for leading dots — measured at ~135us per
    address, so ~135ms for a thousand recipients, all of it to find nothing.

    Returns ``(exact, subtree)``. ``subtree`` holds ".example.com" entries with
    the dot stripped; they match the domain itself and anything under it.
    """
    exact = set()
    subtree = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().lower().lstrip("@")
        if not line:
            continue
        if line.startswith("."):
            canonical = _canonical(line[1:])
            if canonical:
                subtree.add(canonical)
        else:
            canonical = _canonical(line)
            if canonical:
                exact.add(canonical)
    return frozenset(exact), frozenset(subtree)


def _read(path):
    """Parse a blocklist file. A file we cannot use is treated as empty.

    ``UnicodeDecodeError`` is caught alongside ``OSError`` on purpose: it is a
    ``ValueError``, not an ``OSError``, so a file with one bad byte used to
    escape from here and turn every signup into a 500 while making queued mail
    retry until it gave up. Failing open is the documented choice — an
    unreadable blocklist is our problem, and refusing all mail over it is worse
    than missing a block.
    """
    try:
        return _parse(pathlib.Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return frozenset(), frozenset()
    except (OSError, UnicodeError, ValueError):
        logger.exception("blocklist_unreadable", path=str(path))
        return frozenset(), frozenset()


@functools.lru_cache(maxsize=1)
def bundled_domains():
    """The throwaway-provider list that ships with the boilerplate."""
    return _read(BUNDLED_LIST)


@functools.lru_cache(maxsize=1)
def project_domains():
    """The project's own list: the file, plus anything set in settings."""
    path = getattr(settings, "SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE", "") or ""
    exact, subtree = _read(path) if path else (frozenset(), frozenset())
    exact = set(exact)
    subtree = set(subtree)

    for entry in getattr(settings, "SPEEDPY_BLOCKED_EMAIL_DOMAINS", None) or []:
        line = str(entry).strip().lower().lstrip("@")
        if not line:
            continue
        if line.startswith("."):
            subtree.add(_canonical(line[1:]))
        else:
            exact.add(_canonical(line))
    return frozenset(e for e in exact if e), frozenset(e for e in subtree if e)


def clear_cache(**kwargs):
    """Forget both lists.

    Wired to ``setting_changed`` below, so ``override_settings`` in a test takes
    effect without the test remembering to call this. Note that the cache is
    per-process: editing a list file does NOT reach a running web or Celery
    worker, and is not meant to — a deploy is when a list change takes effect.
    """
    bundled_domains.cache_clear()
    project_domains.cache_clear()


@receiver(setting_changed)
def _clear_cache_on_setting_change(sender, setting, **kwargs):
    if setting in (
        "SPEEDPY_BLOCKED_EMAIL_DOMAINS",
        "SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE",
        "SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS",
    ):
        clear_cache()


def _domain_of(email_or_domain):
    """The domain part, from an address in any form Django accepts.

    ``parseaddr`` rather than a bare split, because Django happily sends
    ``"Customer <user@example.com>"`` and splitting at the last ``@`` yields
    ``example.com>`` — which matches nothing, so a display-name recipient walked
    straight past this whole feature. A bare domain is passed through unchanged
    so ``is_blocked("example.com")`` still works.
    """
    value = (email_or_domain or "").strip()
    if not value:
        return ""
    _, addr_spec = parseaddr(value)
    candidate = addr_spec or value
    if "@" in candidate:
        candidate = candidate.rsplit("@", 1)[-1]
    return _canonical(candidate)


def _matches(domain, lists):
    """Whether a canonical domain is covered by ``(exact, subtree)``.

    Exact entries match only themselves. Subtree entries match the domain and
    everything under it. The asymmetry is deliberate: silently blocking every
    subdomain of a bare entry would surprise people, and plenty of products live
    on a subdomain of a domain they do not control.

    Costs one set lookup plus one per label, rather than a walk of the list.
    """
    exact, subtree = lists
    if not domain:
        return False
    if domain in exact:
        return True
    if not subtree:
        return False
    parts = domain.split(".")
    for i in range(len(parts)):
        if ".".join(parts[i:]) in subtree:
            return True
    return False


def is_disposable(email_or_domain):
    """Whether the address belongs to a bundled throwaway-mail provider."""
    return _matches(_domain_of(email_or_domain), bundled_domains())


def is_project_blocked(email_or_domain):
    """Whether the project's own list covers this address."""
    return _matches(_domain_of(email_or_domain), project_domains())


def is_blocked(email_or_domain):
    """Whether we refuse this address at all, from either list.

    The caller is told yes or no and never which list matched, so a refusal
    message cannot leak the reason by accident.
    """
    domain = _domain_of(email_or_domain)
    if not domain:
        return False

    if getattr(settings, "SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS", True) and _matches(
        domain, bundled_domains()
    ):
        logger.info("email_domain_refused", domain=domain, list="bundled")
        return True
    if _matches(domain, project_domains()):
        logger.info("email_domain_refused", domain=domain, list="project")
        return True
    return False
