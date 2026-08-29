"""Team-local time zone: default, selector shortlist, and validation.

``TIME_ZONE`` is normally UTC, so team-local scheduling ("send Tuesday at 9am")
and "today" for a daily counter are undefined without a per-team zone. This
module gives the ``Team`` model its default/validator and the selector its
choices, so the model edit stays a single field plus two thin helpers.

Both the default zone and the selector shortlist are **overridable per project
via settings**, so a project customizes them WITHOUT editing this file:

    DEFAULT_TEAM_TIMEZONE = "Europe/Berlin"            # default for new teams
    TEAM_TIMEZONE_CHOICES = ["UTC", "Europe/Berlin"]   # selector shortlist

Storage is not limited to the shortlist — any valid IANA name validates; the
shortlist only keeps the dropdown readable.
"""

from zoneinfo import ZoneInfo, available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError

# Neutral fallback for a generic boilerplate. A project overrides the effective
# default via ``settings.DEFAULT_TEAM_TIMEZONE``. Always a valid IANA zone, so it
# is the last-resort fallback everywhere below.
FALLBACK_TEAM_TIMEZONE = "UTC"

# Built-in shortlist for the selector UI. A project replaces or extends it via
# ``settings.TEAM_TIMEZONE_CHOICES``.
DEFAULT_COMMON_TIMEZONES = [
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Madrid",
    "Europe/Moscow",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Australia/Sydney",
    "Pacific/Auckland",
]


def get_default_team_timezone():
    """The default zone for new teams — overridable via settings.

    Used as the model field's **callable** default so migrations freeze the
    callable reference, not the value: changing the setting needs no migration.
    """
    return getattr(settings, "DEFAULT_TEAM_TIMEZONE", None) or FALLBACK_TEAM_TIMEZONE


def common_timezones():
    """The selector shortlist — from settings, or the built-in default."""
    return list(
        getattr(settings, "TEAM_TIMEZONE_CHOICES", None) or DEFAULT_COMMON_TIMEZONES
    )


def validate_timezone(value):
    """Raise ``ValidationError`` unless ``value`` is a resolvable IANA zone."""
    try:
        ZoneInfo(value)
    except Exception as exc:  # ZoneInfoNotFoundError and friends
        raise ValidationError(f"{value!r} is not a valid time zone.") from exc


def is_valid_timezone(value):
    return bool(value) and value in available_timezones()


def tz_choices(include=None):
    """``(value, label)`` pairs for the selector — labels are the bare IANA name.

    Offsets are deliberately NOT shown: they are seasonal (DST) and would mislead
    someone scheduling future work; the stored value is the IANA name regardless.

    ``include`` prepends a team's current stored value so it is never dropped
    from its own menu — even if it is not on the shortlist, or is an invalid
    value that slipped past validation (this must not crash the settings page, so
    no ``ZoneInfo()`` call is made here). The result is never empty.
    """
    names = common_timezones() or [FALLBACK_TEAM_TIMEZONE]
    if include:
        names = [include] + names
    seen = set()
    out = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, name))
    return out
