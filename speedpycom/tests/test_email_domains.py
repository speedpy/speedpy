"""Blocking email addresses by domain.

The most valuable test here is the false-positive one. A bad entry in an upstream
pull request would stop signups from a major provider, and the only symptom is a
quiet drop in conversions — nothing errors, nothing logs, and nobody complains
because they cannot sign up to complain.
"""

import pathlib
import tempfile
from unittest import mock

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
        """A missing file degrades to empty sets, which would silently disable
        the whole feature — so assert it is populated."""
        exact, subtree = email_domains.bundled_domains()
        self.assertGreater(len(exact) + len(subtree), 1000)

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
            self.assertEqual(
                email_domains.project_domains(), (frozenset(), frozenset())
            )
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


class SendTimeEnforcementTests(TestCase):
    """A blocked domain must not be mailed, however the address got in.

    Blocking at signup keeps these addresses out of the database, but signup is
    not the only door: a hand-typed team invitation, a CSV import, or an address
    changed after the fact all bypass it. The purpose of the lists is that we do
    not send there, so the rule has to hold at the point of sending too.
    """

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def _backend(self):
        from speedpycom.email_backends import SuppressionAwareEmailBackend

        return SuppressionAwareEmailBackend()

    @staticmethod
    def _message(**kwargs):
        from django.core.mail import EmailMessage

        kwargs.setdefault("subject", "hello")
        kwargs.setdefault("body", "body")
        return EmailMessage(**kwargs)

    def test_a_throwaway_domain_is_not_mailed(self):
        message = self._message(to=["someone@mailinator.com"])
        self.assertEqual(self._backend().send_messages([message]), 0)

    def test_a_project_blocked_domain_is_not_mailed(self):
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS=["rival.example"]):
            email_domains.clear_cache()
            message = self._message(to=["someone@rival.example"])
            self.assertEqual(self._backend().send_messages([message]), 0)

    def test_a_normal_address_still_goes_out(self):
        # Asserted on the return count, not mail.outbox: this wrapper builds its
        # inner backend from EMAIL_PROVIDER, which is `console` in tests, so
        # Django's locmem outbox never sees these messages.
        message = self._message(to=["real@example.com"])
        self.assertEqual(self._backend().send_messages([message]), 1)
        self.assertEqual(message.to, ["real@example.com"])

    def test_only_the_blocked_recipients_are_dropped(self):
        message = self._message(
            to=["real@example.com", "throwaway@mailinator.com"],
            cc=["cc@example.com"],
            bcc=["bcc@mailinator.com"],
        )
        self.assertEqual(self._backend().send_messages([message]), 1)
        self.assertEqual(message.to, ["real@example.com"])
        self.assertEqual(message.cc, ["cc@example.com"])
        self.assertEqual(message.bcc, [])

    def test_turning_the_bundled_list_off_also_stops_the_send_time_block(self):
        """One switch, one meaning. If the project accepts throwaway signups it
        must be able to mail them too, or confirmation would never arrive."""
        with override_settings(SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS=False):
            email_domains.clear_cache()
            message = self._message(to=["someone@mailinator.com"])
            self.assertEqual(self._backend().send_messages([message]), 1)
            self.assertEqual(message.to, ["someone@mailinator.com"])

    def test_a_batch_with_one_bad_message_still_sends_the_others(self):
        good = self._message(to=["real@example.com"])
        bad = self._message(to=["throwaway@mailinator.com"])
        self.assertEqual(self._backend().send_messages([good, bad]), 1)
        self.assertEqual(good.to, ["real@example.com"])
        self.assertEqual(bad.to, [])

    def test_the_subdomain_rule_applies_at_send_time_too(self):
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS=[".corp.example"]):
            email_domains.clear_cache()
            self.assertEqual(
                self._backend().send_messages(
                    [self._message(to=["a@mail.corp.example"])]
                ),
                0,
            )

    def test_an_empty_batch_is_not_an_error(self):
        self.assertEqual(self._backend().send_messages([]), 0)


class AddressSpellingTests(TestCase):
    """A blocked domain must not be reachable by spelling the address
    differently. Both cases below were live bypasses found by review."""

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_a_display_name_recipient_is_still_blocked(self):
        """Django sends "Name <addr>" happily, and splitting at the last @ gave
        `mailinator.com>`, which matched nothing. The whole feature was one
        display name away from being bypassed."""
        for value in (
            "Customer <user@mailinator.com>",
            "<user@mailinator.com>",
            '"Last, First" <user@mailinator.com>',
            "   Customer  <user@mailinator.com>  ",
        ):
            with self.subTest(value=value):
                self.assertTrue(email_domains.is_blocked(value))

    def test_sub_addressing_is_still_blocked(self):
        self.assertTrue(email_domains.is_blocked("user+tag@mailinator.com"))

    def test_unicode_and_punycode_are_the_same_domain(self):
        """The bundled list contains punycode entries, and Django converts a
        Unicode domain to punycode on the way out — so comparing the two forms
        literally would let the Unicode spelling through and then deliver it."""
        self.assertTrue(email_domains.is_blocked("user@xn--5nx.cc"))
        self.assertTrue(email_domains.is_blocked("user@\u7075.cc"))

    def test_a_unicode_list_entry_matches_a_punycode_address(self):
        """The mismatch works in both directions."""
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS=["b\u00fccher.example"]):
            self.assertTrue(email_domains.is_blocked("user@xn--bcher-kva.example"))
            self.assertTrue(email_domains.is_blocked("user@b\u00fccher.example"))

    def test_a_punycode_list_entry_matches_a_unicode_address(self):
        with override_settings(
            SPEEDPY_BLOCKED_EMAIL_DOMAINS=["xn--bcher-kva.example"]
        ):
            self.assertTrue(email_domains.is_blocked("user@b\u00fccher.example"))

    def test_a_domain_that_merely_ends_with_a_blocked_one_is_allowed(self):
        """A bare entry matches itself only. (Do not use notmailinator.com as
        the example — it is genuinely in the bundled list.)"""
        self.assertFalse(email_domains.is_blocked("user@notarealmailinator.com"))
        self.assertFalse(email_domains.is_blocked("user@mailinator.com.evil.example"))

    def test_uppercase_and_padded_list_entries_still_match(self):
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS=["  RIVAL.Example  "]):
            self.assertTrue(email_domains.is_blocked("user@rival.example"))


class CacheInvalidationTests(TestCase):
    """override_settings must take effect without the test remembering to clear.

    A test that has to call clear_cache() by hand is a test that will one day be
    written without it, and then it silently asserts against a stale list.
    """

    def test_override_settings_alone_invalidates_the_cache(self):
        self.assertFalse(email_domains.is_blocked("a@late.example"))
        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS=["late.example"]):
            self.assertTrue(email_domains.is_blocked("a@late.example"))
        self.assertFalse(email_domains.is_blocked("a@late.example"))


class UnreadableListTests(TestCase):
    """A bad file must fail open, not turn every signup into a 500.

    read_text raises UnicodeDecodeError on a bad byte, and that is a ValueError
    rather than an OSError — so it escaped the original handler, broke signup,
    and made queued mail retry until it gave up.
    """

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_invalid_utf8_is_treated_as_an_empty_list(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(b"good.example\n\xff\xfe not utf-8 \n")
        handle.close()
        self.addCleanup(lambda: pathlib.Path(handle.name).unlink(missing_ok=True))

        with override_settings(SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE=handle.name):
            self.assertEqual(email_domains.project_domains(), (frozenset(), frozenset()))
            self.assertFalse(email_domains.is_blocked("a@good.example"))
            # And the bundled list keeps working — one bad file is not fatal.
            self.assertTrue(email_domains.is_blocked("a@mailinator.com"))


class MatchingCostTests(TestCase):
    """A miss must not walk the whole bundled list.

    It used to: ~135us per address, so ~135ms for a thousand recipients, all
    spent finding nothing. Structural rather than timing-based, because a timing
    assertion is flaky on shared CI.
    """

    def test_the_bundled_list_is_split_into_exact_and_subtree_sets(self):
        exact, subtree = email_domains.bundled_domains()
        self.assertIsInstance(exact, frozenset)
        self.assertIsInstance(subtree, frozenset)
        self.assertGreater(len(exact), 1000)

    def test_a_miss_costs_a_bounded_number_of_lookups(self):
        """With no subtree entries a miss is a single set lookup, and with them
        it is one per label — never a scan of the list."""
        exact, subtree = email_domains.bundled_domains()
        self.assertEqual(len(subtree), 0)
        with mock.patch.object(
            email_domains, "_canonical", wraps=email_domains._canonical
        ) as canonical:
            email_domains.is_blocked("someone@allowed.example")
        self.assertLessEqual(canonical.call_count, 2)
