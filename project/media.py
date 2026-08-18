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

from django.core.files.storage import FileSystemStorage

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



class PrivateFileSystemStorage(FileSystemStorage):
    """Local-disk storage for files that must never be fetched by URL.

    Django's ``FileSystemStorage.base_url`` falls back to ``MEDIA_URL`` when it is
    given ``None``, so simply omitting a base URL is not enough — the file would
    still get a working, web-server-served URL. Refuse to produce one at all, and
    say what to do instead.
    """

    def url(self, name):
        raise ValueError(
            "This file is private and has no public URL. Serve it through a view "
            "that checks permissions and returns FileResponse(field.open()), or "
            "switch to object storage (USE_S3=True) for signed URLs."
        )


def private_storage():
    """Storage for files that must not be readable by URL alone.

    Returns the S3 private backend when ``USE_S3`` is on, and local disk otherwise,
    so a model field works in both modes:

        from project.media import private_storage

        class Invoice(models.Model):
            pdf = models.FileField(storage=private_storage, upload_to="invoices/")

    Pass the function itself, not a call — Django accepts a callable and records
    the reference in migrations, so flipping ``USE_S3`` needs no migration.

    In local mode files land in ``PRIVATE_MEDIA_ROOT``, which defaults to a
    directory **outside** ``MEDIA_ROOT`` on purpose: anything under ``MEDIA_ROOT``
    is served by the web server, so a "private" subdirectory there would be public.
    """
    from django.conf import settings

    if getattr(settings, "USE_S3", False):
        from speedpycom.storages import PrivateMediaStorage

        return PrivateMediaStorage()

    return PrivateFileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)
