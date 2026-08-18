"""Object storage configuration: local disk by default, S3 when opted in.

The S3 backend assertions need the optional ``s3`` extra
(``uv sync --extra s3``) and skip cleanly without it, so a default install still
runs a green suite.
"""

from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.test import SimpleTestCase, override_settings

from project.media import private_storage

try:  # the optional extra
    import storages  # noqa: F401

    HAS_S3_EXTRA = True
except ModuleNotFoundError:  # pragma: no cover - depends on install flavour
    HAS_S3_EXTRA = False

S3_ENV = dict(
    USE_S3=True,
    S3_ACCESS_KEY_ID="key",
    S3_SECRET_ACCESS_KEY="secret",
    S3_BUCKET_NAME="bucket",
    S3_REGION_NAME="fra1",
    S3_ENDPOINT_URL="https://fra1.example.com",
    S3_CDN_BASE="",
    S3_DEFAULT_ACL="",
    S3_SEND_PRIVATE_ACL=True,
    S3_SIGNED_URL_EXPIRE=600,
    S3_ADDRESSING_STYLE="",
)


class DefaultsToLocalDiskTests(SimpleTestCase):
    def test_s3_is_off_by_default(self):
        self.assertFalse(settings.USE_S3)

    def test_default_storage_is_local_disk(self):
        self.assertEqual(
            settings.STORAGES["default"]["BACKEND"],
            "django.core.files.storage.FileSystemStorage",
        )

    def test_static_files_stay_on_whitenoise_backend(self):
        """Static must not move to object storage: deploys stay atomic."""
        self.assertEqual(
            settings.STORAGES["staticfiles"]["BACKEND"],
            "django.contrib.staticfiles.storage.StaticFilesStorage",
        )


class PrivateStorageSelectorTests(SimpleTestCase):
    def test_local_mode_stores_outside_media_root(self):
        """Everything under MEDIA_ROOT is served by the web server, so private
        files must live somewhere else entirely."""
        store = private_storage()
        self.assertIsInstance(store, FileSystemStorage)
        self.assertEqual(Path(store.location), Path(settings.PRIVATE_MEDIA_ROOT))
        self.assertNotIn(
            Path(settings.MEDIA_ROOT), Path(store.location).parents
        )
        self.assertNotEqual(Path(store.location), Path(settings.MEDIA_ROOT))

    def test_local_mode_refuses_to_produce_a_url(self):
        """FileSystemStorage.base_url falls back to MEDIA_URL when given None, so
        omitting it is not enough — asking for a URL must fail loudly."""
        store = private_storage()
        with self.assertRaises(ValueError) as ctx:
            store.url("invoices/secret.pdf")
        self.assertIn("private", str(ctx.exception).lower())

    @skipUnless(HAS_S3_EXTRA, "requires: uv sync --extra s3")
    @override_settings(**S3_ENV)
    def test_s3_mode_returns_the_private_s3_backend(self):
        from speedpycom.storages import PrivateMediaStorage

        self.assertIsInstance(private_storage(), PrivateMediaStorage)


@skipUnless(HAS_S3_EXTRA, "requires: uv sync --extra s3")
@override_settings(**S3_ENV)
class S3BackendTests(SimpleTestCase):
    def test_prefixes_are_disjoint(self):
        from speedpycom.storages import PrivateMediaStorage, PublicMediaStorage

        self.assertEqual(PublicMediaStorage().location, "media")
        self.assertEqual(PrivateMediaStorage().location, "private")

    def test_public_urls_are_unsigned_private_urls_are_signed(self):
        from speedpycom.storages import PrivateMediaStorage, PublicMediaStorage

        self.assertFalse(PublicMediaStorage().querystring_auth)
        self.assertTrue(PrivateMediaStorage().querystring_auth)

    def test_no_acl_is_sent_by_default(self):
        """Portability: AWS buckets with ACLs disabled reject any ACL, and R2 has
        no ACLs at all. Sending none works everywhere."""
        from speedpycom.storages import PublicMediaStorage

        self.assertIsNone(PublicMediaStorage().default_acl)

    @override_settings(S3_DEFAULT_ACL="public-read")
    def test_acl_is_sent_when_configured(self):
        from speedpycom.storages import PublicMediaStorage

        self.assertEqual(PublicMediaStorage().default_acl, "public-read")

    def test_private_backend_sends_private_acl_by_default(self):
        from speedpycom.storages import PrivateMediaStorage

        self.assertEqual(PrivateMediaStorage().default_acl, "private")

    @override_settings(S3_SEND_PRIVATE_ACL=False)
    def test_private_acl_can_be_suppressed_for_acl_less_providers(self):
        from speedpycom.storages import PrivateMediaStorage

        self.assertIsNone(PrivateMediaStorage().default_acl)

    def test_signed_url_lifetime_follows_the_setting(self):
        from speedpycom.storages import PrivateMediaStorage

        self.assertEqual(PrivateMediaStorage().querystring_expire, 600)

    @override_settings(S3_CDN_BASE="https://cdn.example.com")
    def test_cdn_base_becomes_the_public_custom_domain(self):
        from speedpycom.storages import PublicMediaStorage

        self.assertEqual(PublicMediaStorage().custom_domain, "cdn.example.com")

    def test_no_cdn_means_no_custom_domain(self):
        from speedpycom.storages import PublicMediaStorage

        self.assertFalse(PublicMediaStorage().custom_domain)

    def test_credentials_come_from_settings_not_ambient_aws_vars(self):
        """This project also uses AWS_SES_* for email; storage credentials must be
        passed explicitly so boto3 never picks up an unrelated AWS_* variable."""
        from speedpycom.storages import PublicMediaStorage

        store = PublicMediaStorage()
        self.assertEqual(store.access_key, "key")
        self.assertEqual(store.secret_key, "secret")
        self.assertEqual(store.bucket_name, "bucket")
        self.assertEqual(store.endpoint_url, "https://fra1.example.com")
