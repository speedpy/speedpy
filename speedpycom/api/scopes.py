"""
Scope registry for PAT and OAuth2 tokens.

Single source of truth: ``settings.OAUTH2_PROVIDER["SCOPES"]``.

Fork owners register custom scopes by adding entries to that dict
(follow the ``read:<domain>`` / ``write:<domain>`` convention).
"""

from django.conf import settings


def get_scope_registry() -> dict[str, str]:
    """Return ``{scope_name: description}`` from settings."""
    return dict(settings.OAUTH2_PROVIDER.get("SCOPES", {}))


def get_scope_choices() -> list[tuple[str, str]]:
    """Return ``[(name, "name — description"), ...]`` for form widgets."""
    return [(k, f"{k} — {v}") for k, v in get_scope_registry().items()]


def is_valid_scope(scope: str) -> bool:
    """Return True if *scope* is registered."""
    return scope in get_scope_registry()


def validate_scopes(scopes: list[str]) -> list[str]:
    """Return list of unknown scope names (empty if all valid)."""
    registry = get_scope_registry()
    return [s for s in scopes if s not in registry]
