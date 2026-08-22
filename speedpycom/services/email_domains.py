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

import structlog
from django.conf import settings
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


def _parse(text):
    """Domains from a blocklist file: one per line, `#` comments, blank lines."""
    found = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().lower().lstrip("@")
        if line:
            found.add(line)
    return found


@functools.lru_cache(maxsize=1)
def bundled_domains():
    """The throwaway-provider list that ships with the boilerplate."""
    try:
        return frozenset(_parse(BUNDLED_LIST.read_text(encoding="utf-8")))
    except OSError:
        # Missing file must not break signup. An unreadable blocklist is our
        # problem, and refusing every signup over it would be a worse outcome
        # than accepting a throwaway address.
        logger.exception("disposable_blocklist_unreadable", path=str(BUNDLED_LIST))
        return frozenset()


@functools.lru_cache(maxsize=1)
def project_domains():
    """The project's own list: the file, plus anything set in settings."""
    domains = set()

    path = getattr(settings, "SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE", "") or ""
    if path:
        try:
            domains |= _parse(pathlib.Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Absent is normal — a project with nothing to add never creates it.
            pass
        except OSError:
            logger.exception("project_blocklist_unreadable", path=str(path))

    for entry in getattr(settings, "SPEEDPY_BLOCKED_EMAIL_DOMAINS", None) or []:
        cleaned = str(entry).strip().lower().lstrip("@")
        if cleaned:
            domains.add(cleaned)
    return frozenset(domains)


def clear_cache():
    """Forget both lists. For tests, and after editing a list at runtime."""
    bundled_domains.cache_clear()
    project_domains.cache_clear()


def _domain_of(email_or_domain):
    value = (email_or_domain or "").strip().lower().rstrip(".")
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    return value


def _matches(domain, blocklist):
    """Exact match, plus `.example.com` entries covering subdomains.

    A bare `example.com` entry matches only that domain — deliberately. Blocking
    every subdomain of a bare entry would be a surprise, and some products live
    on a subdomain of a domain they do not control.
    """
    if not domain:
        return False
    if domain in blocklist:
        return True
    for entry in blocklist:
        if entry.startswith(".") and (
            domain == entry[1:] or domain.endswith(entry)
        ):
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
