"""MEDIA_URL normalization for platform-provided volume environment variables.

Appliku volumes derive TWO environment variables from the volume's
"environment variable" prefix: ``<PREFIX>_ROOT`` gets the container path and
``<PREFIX>_URL`` gets the web-server path. So a volume whose prefix is ``MEDIA``
sets ``MEDIA_ROOT`` and ``MEDIA_URL`` — not a bare ``MEDIA``.

Two traps come with that, and both are handled here:

1. ``_URL`` is set even when the volume has no web-server path. The value then
   arrives as the literal string ``"None"``, which would silently become Django's
   ``MEDIA_URL`` and break every media link.
2. Django expects ``MEDIA_URL`` to end in a slash. A prefix typed without one
   yields subtly wrong URLs rather than an error.
"""

DEFAULT_MEDIA_URL = "/media/"

#: Values that mean "the platform set this variable but there is nothing in it".
_EMPTY_SENTINELS = frozenset({"", "none", "null"})


def normalize_media_url(raw, default=DEFAULT_MEDIA_URL):
    """Return a usable ``MEDIA_URL`` from a raw environment value."""
    value = (raw or "").strip()
    if value.lower() in _EMPTY_SENTINELS:
        value = default
    if not value.endswith("/"):
        value += "/"
    return value
