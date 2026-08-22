"""Blocking email addresses by domain.

The most valuable test here is the false-positive one. A bad entry in an upstream
pull request would stop signups from a major provider, and the only symptom is a
quiet drop in conversions — nothing errors, nothing logs, and nobody complains
because they cannot sign up to complain.
"""

import pathlib
import tempfile

from django.test import TestCase, override_settings

from speedpycom.services import email_domains

#: Providers that must never appear in the bundled list. Anyone refused here is
#: a real customer.
REAL_PROVIDERS = [
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "me.com",
    "protonmail.com",
    "proton.me",
    "fastmail.com",
    "aol.com",
    "gmx.com",
    "gmx.de",
    "zoho.com",
    "yandex.com",
    "qq.com",
    "web.de",
    "mail.ru",
    "live.com",
    "msn.com",
]


class BundledListTests(TestCase):
    def setUp(self):
        email_domains.clear_cache()

    def test_the_bundled_list_blocks_no_real_provider(self):
        """The one that matters. See the module docstring."""
        blocked = [d for d in REAL_PROVIDERS if email_domains.is_disposable(d)]
        self.assertEqual(
            blocked,
            [],
            f"the bundled list would refuse real providers: {blocked}. "
            "Check the last refresh — see speedpycom/data/README.md.",
        )

    def test_known_throwaway_providers_are_blocked(self):
        for domain in ("mailinator.com", "guerrillamail.com", "10minutemail.com"):
            with self.subTest(domain=domain):
                self.assertTrue(email_domains.is_disposable(domain))

    def test_the_list_is_actually_loaded(self):
        """A missing file degrades to an empty set, which would silently disable
        the whole feature — so assert it is populated."""
        self.assertGreater(len(email_domains.bundled_domains()), 1000)

    def test_a_full_address_and_a_bare_domain_both_work(self):
        self.assertTrue(email_domains.is_disposable("someone@mailinator.com"))
        self.assertTrue(email_domains.is_disposable("mailinator.com"))

    def test_matching_ignores_case_and_a_trailing_dot(self):
        for value in ("Someone@MAILINATOR.com", "someone@mailinator.com.", "MAILINATOR.COM"):
            with self.subTest(value=value):
                self.assertTrue(email_domains.is_disposable(value))


class ProjectListTests(TestCase):
    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def _file(self, contents):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        handle.write(contents)
        handle.close()
        self.addCleanup(lambda: pathlib.Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def test_a_domain_in_the_project_file_is_blocked(self):
        path = self._file("# a comment\n\nrival.example\n")
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=path):
            email_domains.clear_cache()
            self.assertTrue(email_domains.is_blocked("someone@rival.example"))
            self.assertFalse(email_domains.is_blocked("someone@allowed.example"))

    def test_comments_and_blank_lines_are_ignored(self):
        path = self._file("# rival.example is a comment, not an entry\n\n   \n")
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=path):
            email_domains.clear_cache()
            self.assertFalse(email_domains.is_blocked("someone@rival.example"))

    def test_a_leading_dot_covers_subdomains_and_the_domain_itself(self):
        path = self._file(".corp.example\n")
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=path):
            email_domains.clear_cache()
            self.assertTrue(email_domains.is_blocked("a@mail.corp.example"))
            self.assertTrue(email_domains.is_blocked("a@corp.example"))
            self.assertFalse(email_domains.is_blocked("a@notcorp.example"))

    def test_a_bare_entry_does_not_cover_subdomains(self):
        """Blocking every subdomain of a bare entry would be a surprise."""
        path = self._file("corp.example\n")
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=path):
            email_domains.clear_cache()
            self.assertTrue(email_domains.is_blocked("a@corp.example"))
            self.assertFalse(email_domains.is_blocked("a@mail.corp.example"))

    def test_a_missing_file_is_not_an_error(self):
        with override_settings(
            SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE="/nonexistent/nope.txt"
        ):
            email_domains.clear_cache()
            self.assertEqual(email_domains.project_domains(), frozenset())
            self.assertFalse(email_domains.is_blocked("a@example.com"))

    def test_the_setting_and_the_file_are_merged_not_replaced(self):
        path = self._file("fromfile.example\n")
        with override_settings(
            SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=path,
            SPEEDPY_BLOCKED_EMAIL_DOMAINS=["fromenv.example"],
        ):
            email_domains.clear_cache()
            self.assertTrue(email_domains.is_blocked("a@fromfile.example"))
            self.assertTrue(email_domains.is_blocked("a@fromenv.example"))


class SwitchTests(TestCase):
    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_the_bundled_list_can_be_turned_off(self):
        with override_settings(SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS=False):
            self.assertFalse(email_domains.is_blocked("a@mailinator.com"))

    def test_turning_it_off_does_not_disable_the_project_list(self):
        """Two lists, two decisions. Switching off the bundled one must not
        quietly stop enforcing the project's own."""
        path = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        path.write("rival.example\n")
        path.close()
        self.addCleanup(lambda: pathlib.Path(path.name).unlink(missing_ok=True))
        with override_settings(
            SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS=False,
            SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=path.name,
        ):
            email_domains.clear_cache()
            self.assertFalse(email_domains.is_blocked("a@mailinator.com"))
            self.assertTrue(email_domains.is_blocked("a@rival.example"))

    def test_an_empty_or_odd_value_is_not_blocked(self):
        for value in ("", None, "   ", "no-at-sign", "@"):
            with self.subTest(value=value):
                self.assertFalse(email_domains.is_blocked(value))


class SignupFormTests(TestCase):
    """The refusal has to reach the form, and say nothing useful."""

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_signup_with_a_throwaway_address_is_refused(self):
        response = self.client.post(
            "/accounts/signup/",
            {
                "email": "someone@mailinator.com",
                "password1": "sup3r-Secret-pass!",
                "tos": "on",
                "dpa": "on",
            },
        )
        self.assertEqual(response.status_code, 200)  # redisplayed with an error
        self.assertContains(response, "cannot accept this email address")

    def test_the_message_does_not_reveal_why(self):
        """Naming the reason tells somebody probing the filter what to try."""
        response = self.client.post(
            "/accounts/signup/",
            {
                "email": "someone@mailinator.com",
                "password1": "sup3r-Secret-pass!",
                "tos": "on",
                "dpa": "on",
            },
        )
        body = response.content.decode().lower()
        for leak in ("disposable", "throwaway", "blocklist", "blacklist", "mailinator is"):
            self.assertNotIn(leak, body)
