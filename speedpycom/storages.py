"""S3-compatible object storage backends (opt-in).

Local disk is the default. Set ``USE_S3=True`` plus the ``S3_*`` variables to move
media to any S3-compatible provider — AWS S3, DigitalOcean Spaces, Cloudflare R2,
Wasabi, Backblaze B2, MinIO. Nothing here is provider-specific: the provider is
chosen entirely by ``S3_ENDPOINT_URL``.

Two backends, one bucket, disjoint prefixes and opposite policies:

| Backend              | Prefix     | Access                                  |
|----------------------|------------|-----------------------------------------|
| PublicMediaStorage   | ``media/`` | readable by URL, optionally via a CDN   |
| PrivateMediaStorage  | ``private/``| short-lived signed URLs only            |

``PublicMediaStorage`` is wired as ``STORAGES["default"]`` when ``USE_S3`` is on.
``PrivateMediaStorage`` is opt-in per field — see ``private_storage()`` in
``project/media.py``, which returns the right backend in both modes so a model
field does not have to care.

This module imports ``django-storages``, which is an optional dependency:

    uv sync --extra s3

It is only imported when ``USE_S3`` is on (Django resolves ``STORAGES`` backends
lazily by dotted path), so default installs never need boto3.

**ACLs are not portable.** ``S3_DEFAULT_ACL`` defaults to unset, which works
everywhere. DigitalOcean Spaces supports per-object ACLs, so set it to
``public-read`` there. AWS buckets created since April 2023 default to
*bucket owner enforced*, which disables ACLs and **rejects** any request carrying
one; Cloudflare R2 does not implement ACLs at all. On those, leave it unset and
grant public read with a bucket policy or a public bucket / custom domain.
"""

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


def _cdn_host():
    """Host portion of ``S3_CDN_BASE``, or None when no CDN is configured."""
    base = getattr(settings, "S3_CDN_BASE", "") or ""
    return base.split("//")[-1].rstrip("/") or None if base else None


class _S3Storage(S3Boto3Storage):
    """Shared connection settings; subclasses set the prefix and the policy.

    Credentials are passed explicitly rather than left to boto3's environment
    lookup, so an unrelated ``AWS_*`` variable in the environment (this project
    also uses ``AWS_SES_*`` for email) can never silently redirect uploads.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("access_key", settings.S3_ACCESS_KEY_ID)
        kwargs.setdefault("secret_key", settings.S3_SECRET_ACCESS_KEY)
        kwargs.setdefault("bucket_name", settings.S3_BUCKET_NAME)
        if getattr(settings, "S3_REGION_NAME", ""):
            kwargs.setdefault("region_name", settings.S3_REGION_NAME)
        if getattr(settings, "S3_ENDPOINT_URL", ""):
            kwargs.setdefault("endpoint_url", settings.S3_ENDPOINT_URL)
        if getattr(settings, "S3_ADDRESSING_STYLE", ""):
            # MinIO and some self-hosted gateways need "path".
            kwargs.setdefault("addressing_style", settings.S3_ADDRESSING_STYLE)
        # Never overwrite an existing key: uploads get a suffixed name instead.
        kwargs.setdefault("file_overwrite", False)
        super().__init__(**kwargs)


class PublicMediaStorage(_S3Storage):
    """User-visible media: avatars, logos, attachments. Plain (unsigned) URLs."""

    location = "media"
    querystring_auth = False  # plain URLs, no signature
    object_parameters = {"CacheControl": "public, max-age=86400"}

    def __init__(self, **kwargs):
        acl = getattr(settings, "S3_DEFAULT_ACL", "") or None
        kwargs.setdefault("default_acl", acl)
        host = _cdn_host()
        if host:
            # Serve from the CDN edge rather than the bucket origin.
            kwargs.setdefault("custom_domain", host)
        super().__init__(**kwargs)


class PrivateMediaStorage(_S3Storage):
    """Files that must not be readable by URL alone.

    ``default_acl="private"`` is safe to send even on ACL-disabled buckets in the
    common case, but if your provider rejects it outright, set
    ``S3_SEND_PRIVATE_ACL=False`` and rely on the bucket being private by default
    — which it is, unless you have deliberately opened it up.
    """

    location = "private"
    querystring_auth = True  # signed URLs only

    def __init__(self, **kwargs):
        if getattr(settings, "S3_SEND_PRIVATE_ACL", True):
            kwargs.setdefault("default_acl", "private")
        kwargs.setdefault(
            "querystring_expire", getattr(settings, "S3_SIGNED_URL_EXPIRE", 600)
        )
        super().__init__(**kwargs)
