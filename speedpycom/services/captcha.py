"""Provider-agnostic CAPTCHA verification for PUBLIC (unauthenticated) forms.

Django's own auth forms get their CAPTCHA from ``django-recaptcha``'s form
field, which is the right tool there: a login form either passes or it does
not. A public data plane is different, and this module exists because of one
distinction that field cannot make.

**A broken token and a low score are not the same event.**

``ReCaptchaField`` treats both as a field error, so a visitor whose score came
back at 0.3 is refused exactly like a visitor who sent no token at all. On a
form that collects a customer's testimonial that is the wrong trade: reCAPTCHA
v3 returns a probability, not a verdict, and throwing away a real testimonial
because a person browses with a strict privacy extension is worse than letting
one more item into a queue a human already reviews. So:

``failed`` / ``absent``
    The request is malformed — no token, a token the provider rejects, a reused
    or expired one. The caller REFUSES. This is not a judgement about the
    visitor; the request simply is not one our own page could have produced.

``low_score``
    The provider verified the token and thinks the visitor is probably a bot.
    The caller ACCEPTS and records the score, so whoever reviews the item can
    see it. Callers must not reject on this.

``unavailable``
    We could not get an answer, or the answer says OUR configuration is wrong
    (a bad secret refuses *every* visitor, so it cannot be treated as the
    visitor's fault). Fails OPEN, logged loudly — the same posture as the
    Redis-backed abuse caps. A provider outage must not stop a customer
    collecting.

``disabled``
    No keys configured. The whole feature is inert, which is how it stays off
    until somebody sets both env vars.

Swapping provider is a setting, not a rewrite: ``CAPTCHA_PROVIDER`` names a
callable taking ``(token, *, remote_ip)`` and returning a
:class:`ProviderVerdict`. A provider with no score concept (reCAPTCHA v2,
Turnstile) returns ``score=None`` and can therefore never produce
``low_score``.
"""

import dataclasses

import structlog
from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string

logger = structlog.get_logger(__name__)

#: The provider verified the token and the score (if any) is above the floor.
OUTCOME_OK = "ok"
#: Verified, but the provider thinks this is probably automated. NOT a refusal.
OUTCOME_LOW_SCORE = "low_score"
#: No token was presented at all.
OUTCOME_ABSENT = "absent"
#: A token was presented and the provider rejected it.
OUTCOME_FAILED = "failed"
#: No usable answer — provider unreachable, or our own keys are wrong.
OUTCOME_UNAVAILABLE = "unavailable"
#: Not configured; nothing was checked.
OUTCOME_DISABLED = "disabled"

#: Error codes that mean the SITE is misconfigured rather than the visitor being
#: suspect. A wrong secret refuses every single visitor, so treating these as a
#: failed token would take collection down site-wide and look like an attack.
SITE_ERROR_CODES = frozenset(
    {
        "invalid-input-secret",
        "missing-input-secret",
        "bad-request",
        "invalid-keys",
    }
)


@dataclasses.dataclass(frozen=True)
class ProviderVerdict:
    """What a provider says about one token. Providers return this; policy
    (the score floor, what refuses, what only flags) lives in :func:`verify`
    so every provider is governed the same way."""

    ok: bool = False
    #: ``None`` when the provider has no score concept — then no low_score.
    score: float | None = None
    hostname: str = ""
    action: str = ""
    error_codes: tuple = ()
    #: True when we never got an answer, or the answer blames our own config.
    unavailable: bool = False


@dataclasses.dataclass(frozen=True)
class CaptchaResult:
    outcome: str
    score: float | None = None
    provider: str = ""
    hostname: str = ""
    action: str = ""
    error_codes: tuple = ()

    @property
    def refuses(self):
        """True only for a request our own page could not have produced.

        A low score is deliberately absent from this list — see the module
        docstring. Callers that guard an EXPENSIVE side effect and want to
        refuse on suspicion must say so explicitly at the call site.
        """
        return self.outcome in (OUTCOME_ABSENT, OUTCOME_FAILED)

    @property
    def suspicious(self):
        return self.outcome == OUTCOME_LOW_SCORE

    @property
    def checked(self):
        """The provider actually answered about this token."""
        return self.outcome in (OUTCOME_OK, OUTCOME_LOW_SCORE, OUTCOME_FAILED)

    def as_metadata(self):
        """A small JSON-safe dict to store next to the record it describes.

        Deliberately not the raw provider payload: that carries a timestamp and
        a hostname we have no reason to keep, and storing whatever a third party
        chose to send is how PII arrives in a JSON column by accident.
        """
        data = {"outcome": self.outcome, "provider": self.provider}
        if self.score is not None:
            data["score"] = self.score
        return data


def enabled():
    """CAPTCHA is active only when both keys are configured.

    Same convention as ``usermodel.forms.recaptcha_enabled`` — empty keys mean
    the feature does not exist, so a fresh checkout runs with no CAPTCHA and
    without any extra flag to remember.
    """
    return bool(
        getattr(settings, "RECAPTCHA_PUBLIC_KEY", "")
        and getattr(settings, "RECAPTCHA_PRIVATE_KEY", "")
    )


def site_key():
    """The public key a template needs, or "" when disabled."""
    return getattr(settings, "RECAPTCHA_PUBLIC_KEY", "") if enabled() else ""


def min_score():
    return float(getattr(settings, "CAPTCHA_MIN_SCORE", 0.5))


_provider_cache = {}


def provider():
    """Resolve ``CAPTCHA_PROVIDER`` once per process."""
    path = getattr(
        settings, "CAPTCHA_PROVIDER", "speedpycom.services.captcha.recaptcha_v3"
    )
    if path not in _provider_cache:
        _provider_cache[path] = import_string(path)
    return _provider_cache[path]


@receiver(setting_changed)
def _reset_provider_cache(sender, setting, **kwargs):
    if setting == "CAPTCHA_PROVIDER":
        _provider_cache.clear()


def recaptcha_v3(token, *, remote_ip=""):
    """Bundled provider: Google reCAPTCHA v3 via ``django_recaptcha``.

    ``django_recaptcha.client.submit`` is used rather than ``httpx`` on purpose
    — it already reads ``RECAPTCHA_DOMAIN``, ``RECAPTCHA_PROXY`` and
    ``RECAPTCHA_VERIFY_REQUEST_TIMEOUT``, so the auth path and the public plane
    cannot end up talking to different endpoints with different timeouts.

    Every exception becomes ``unavailable``: urllib raises a different type for
    a DNS failure, a TLS failure, a timeout and a truncated body, and there is
    no version of "Google is having a bad day" that should refuse a customer's
    testimonial.
    """
    from django_recaptcha import client

    try:
        response = client.submit(
            token, settings.RECAPTCHA_PRIVATE_KEY, remote_ip or ""
        )
    except Exception:
        logger.exception("captcha_provider_unreachable", provider="recaptcha_v3")
        return ProviderVerdict(unavailable=True)

    codes = tuple(response.error_codes or ())
    if not response.is_valid and SITE_ERROR_CODES.intersection(codes):
        # OUR problem, not the visitor's. Loud, because every visitor is
        # affected and nothing else in the system will notice.
        logger.error(
            "captcha_misconfigured", provider="recaptcha_v3", error_codes=codes
        )
        return ProviderVerdict(unavailable=True, error_codes=codes)

    extra = response.extra_data or {}
    raw_score = extra.get("score")
    try:
        score = float(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        score = None
    return ProviderVerdict(
        ok=bool(response.is_valid),
        score=score,
        hostname=str(extra.get("hostname", ""))[:255],
        action=str(response.action or "")[:64],
        error_codes=codes,
    )


def verify(token, *, remote_ip="", expected_action="", floor=None):
    """Check one token and classify the answer. Never raises.

    ``expected_action`` guards against a token minted for a cheap action being
    replayed against an expensive one: reCAPTCHA v3 signs the action name into
    the token, so a mismatch means the token was not made for this endpoint.
    Passing "" skips the check, for providers that carry no action.
    """
    if not enabled():
        return CaptchaResult(outcome=OUTCOME_DISABLED)
    if not (token or "").strip():
        return CaptchaResult(outcome=OUTCOME_ABSENT, provider=_provider_name())

    verdict = provider()(token, remote_ip=remote_ip)
    name = _provider_name()

    if verdict.unavailable:
        return CaptchaResult(
            outcome=OUTCOME_UNAVAILABLE,
            provider=name,
            error_codes=verdict.error_codes,
        )
    if not verdict.ok:
        logger.info(
            "captcha_token_rejected", provider=name, error_codes=verdict.error_codes
        )
        return CaptchaResult(
            outcome=OUTCOME_FAILED, provider=name, error_codes=verdict.error_codes
        )
    if expected_action and verdict.action and verdict.action != expected_action:
        logger.warning(
            "captcha_action_mismatch",
            provider=name,
            expected=expected_action,
            got=verdict.action,
        )
        return CaptchaResult(
            outcome=OUTCOME_FAILED,
            provider=name,
            score=verdict.score,
            action=verdict.action,
            error_codes=("action-mismatch",),
        )

    threshold = min_score() if floor is None else float(floor)
    outcome = OUTCOME_OK
    if verdict.score is not None and verdict.score < threshold:
        outcome = OUTCOME_LOW_SCORE
        logger.info(
            "captcha_low_score",
            provider=name,
            score=verdict.score,
            threshold=threshold,
        )
    return CaptchaResult(
        outcome=outcome,
        score=verdict.score,
        provider=name,
        hostname=verdict.hostname,
        action=verdict.action,
    )


def _provider_name():
    return getattr(
        settings, "CAPTCHA_PROVIDER", "speedpycom.services.captcha.recaptcha_v3"
    ).rsplit(".", 1)[-1]
