"""MEDIA_URL normalization (project/media.py).

Regression cover for a real misconfiguration: Appliku volumes export
``<PREFIX>_ROOT`` and ``<PREFIX>_URL``, settings used to read ``MEDIA_PATH`` for
the URL (a name the platform never sets), and the platform emits ``_URL`` as the
literal string ``"None"`` when the volume has no web-server path.
"""

from django.conf import settings
from django.test import SimpleTestCase

from project.media import DEFAULT_MEDIA_URL, normalize_media_url


class NormalizeMediaURLTests(SimpleTestCase):
    def test_unset_falls_back_to_default(self):
        for raw in ("", "   ", None):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_media_url(raw), DEFAULT_MEDIA_URL)

    def test_literal_none_string_is_treated_as_unset(self):
        """Appliku sets <PREFIX>_URL even with no web path; the value arrives as
        the string "None", which must never become MEDIA_URL."""
        for raw in ("None", "none", "NONE", " None ", "null"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_media_url(raw), DEFAULT_MEDIA_URL)

    def test_platform_value_is_honoured(self):
        self.assertEqual(normalize_media_url("/uploads/"), "/uploads/")

    def test_missing_trailing_slash_is_added(self):
        self.assertEqual(normalize_media_url("/uploads"), "/uploads/")
        self.assertEqual(
            normalize_media_url("https://cdn.example.com/media"),
            "https://cdn.example.com/media/",
        )

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(normalize_media_url("  /uploads/  "), "/uploads/")

    def test_custom_default_is_respected(self):
        self.assertEqual(normalize_media_url("None", default="/files/"), "/files/")


class MediaSettingsInvariantTests(SimpleTestCase):
    def test_configured_media_url_is_sane(self):
        self.assertTrue(settings.MEDIA_URL.endswith("/"))
        self.assertNotIn(settings.MEDIA_URL.strip("/").lower(), {"none", "null"})
