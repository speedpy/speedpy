"""The shared deliverability validator (speedpycom/services/email_deliverability.py).

The reason to have it at all is asymmetric cost: a bounce is charged against the
SES account's bounce rate, and above roughly 5% SES stops sending anything. So
the tests below are mostly about the two ways this can be wrong, which are not
equally bad:

* **refusing a real person** — annoying, and they may not come back;
* **failing open when we should have refused** — invisible, and it accumulates.

Which is why every "we did not get an answer" case fails OPEN and is tested for
it, while the two cases that ARE answers (NXDOMAIN, NoAnswer) refuse. Getting
that backwards would turn one broken resolver into a signup outage.
"""

from unittest import mock

import dns.exception
import dns.resolver
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from speedpycom.services import email_deliverability as deliver

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

ON = {"EMAIL_DELIVERABILITY_CHECK": True, "SIGNUP_EMAIL_MX_CHECK": True, "CACHES": LOCMEM}


class FakeMX:
    def __init__(self, exchange):
        self.exchange = exchange


def resolving(*exchanges):
    return mock.patch.object(
        dns.resolver, "resolve", return_value=[FakeMX(e) for e in exchanges]
    )


def failing(exc):
    return mock.patch.object(dns.resolver, "resolve", side_effect=exc)


@override_settings(**ON)
class VerdictTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_domain_with_mx_is_deliverable(self):
        with resolving("mx.example.com."):
            v = deliver.check("someone@example.com")
        self.assertEqual(v.outcome, deliver.OUTCOME_OK)
        self.assertFalse(v.rejects)
        self.assertEqual(v.message, "")

    def test_nxdomain_refuses(self):
        with failing(dns.resolver.NXDOMAIN()):
            v = deliver.check("someone@nope.example")
        self.assertEqual(v.outcome, deliver.OUTCOME_NO_MX)
        self.assertTrue(v.rejects)
        self.assertIn("typos", str(v.message))

    def test_no_answer_refuses(self):
        with failing(dns.resolver.NoAnswer()):
            self.assertTrue(deliver.check("a@b.example").rejects)

    def test_an_empty_mx_set_refuses(self):
        with resolving():
            self.assertTrue(deliver.check("a@b.example").rejects)

    def test_a_null_mx_refuses(self):
        """RFC 7505: a single "." is a domain saying explicitly that it neither
        sends nor receives mail. Treating it as a valid MX host would accept
        every address at a domain that has told us not to."""
        with resolving("."):
            self.assertTrue(deliver.check("a@b.example").rejects)

    # ---- the fail-open half ----

    def test_a_timeout_does_not_refuse(self):
        with failing(dns.exception.Timeout()):
            v = deliver.check("someone@example.com")
        self.assertEqual(v.outcome, deliver.OUTCOME_UNKNOWN)
        self.assertFalse(v.rejects)

    def test_a_servfail_does_not_refuse(self):
        """NoNameservers means every server refused or SERVFAIL'd. Not the same
        as "no record" — a broken zone must not cost us a real customer."""
        with failing(dns.resolver.NoNameservers()):
            self.assertFalse(deliver.check("someone@example.com").rejects)

    def test_an_unexpected_resolver_error_does_not_refuse(self):
        """A resolver surprise must not become a 500 on a public form."""
        with failing(RuntimeError("resolver exploded")):
            self.assertFalse(deliver.check("someone@example.com").rejects)

    # ---- the cheap checks come first ----

    def test_a_blank_address_is_fine(self):
        """Whether the field is required is the caller's business. Answering
        "malformed" here would make every caller special-case an empty value."""
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertFalse(deliver.check(value).rejects)

    def test_a_blank_address_costs_no_dns(self):
        with mock.patch.object(dns.resolver, "resolve") as resolve:
            deliver.check("")
            resolve.assert_not_called()

    def test_a_blocked_domain_is_refused_without_dns(self):
        """Two set lookups against data already in memory. No reason to pay for
        DNS to reject mailinator.com."""
        with override_settings(BLOCKED_EMAIL_DOMAINS_EXTRA=["spam.example"]):
            with mock.patch.object(
                deliver, "is_blocked", return_value=True
            ), mock.patch.object(dns.resolver, "resolve") as resolve:
                v = deliver.check("a@spam.example")
            resolve.assert_not_called()
        self.assertEqual(v.outcome, deliver.OUTCOME_BLOCKED)
        self.assertTrue(v.rejects)

    def test_a_blocklist_refusal_says_nothing_about_why(self):
        """One wording for every refusal, so somebody probing the filter learns
        nothing about which list matched — and it must NOT be the actionable
        "check for typos" message, which would say "your domain is fine, the
        problem is elsewhere"."""
        with mock.patch.object(deliver, "is_blocked", return_value=True):
            blocked = deliver.check("a@spam.example").message
        with failing(dns.resolver.NXDOMAIN()):
            no_mx = deliver.check("a@nope.example").message
        self.assertNotEqual(str(blocked), str(no_mx))
        self.assertNotIn("typo", str(blocked))

    def test_a_blocklist_is_enforced_even_when_dns_checking_is_off(self):
        """A blocklist is a policy, not a probe. Switching off the DNS lookup
        must not switch off a decision about who we will mail."""
        with override_settings(EMAIL_DELIVERABILITY_CHECK=False):
            with mock.patch.object(deliver, "is_blocked", return_value=True):
                self.assertTrue(deliver.check("a@spam.example").rejects)

    def test_an_address_with_no_at_sign_is_malformed_and_costs_no_dns(self):
        """email_domains' parser passes a bare domain straight through, because
        `is_blocked("example.com")` has to work — so without this, "gmail" would
        have spent two seconds of a public request asking DNS about a hostname."""
        with mock.patch.object(dns.resolver, "resolve") as resolve:
            v = deliver.check("not-an-address")
        resolve.assert_not_called()
        self.assertEqual(v.outcome, deliver.OUTCOME_MALFORMED)
        self.assertTrue(v.rejects)

    def test_a_display_name_address_is_parsed(self):
        """`"Customer <user@example.com>"` splitting at the last @ yields
        `example.com>`, which resolves to nothing. That exact bug was a live
        bypass in the blocklist once, which is why this reuses email_domains'
        parser rather than doing its own split."""
        with resolving("mx.example.com.") as resolve:
            deliver.check("Customer <user@example.com>")
        self.assertEqual(resolve.call_args.args[0], "example.com")


@override_settings(**ON)
class CachingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_second_address_at_the_same_domain_costs_no_dns(self):
        """The defect that made the inline version unusable on an import: one
        lookup per ROW. Cached on the domain, so five thousand gmail addresses
        cost one question."""
        with resolving("mx.example.com.") as resolve:
            deliver.check("one@example.com")
            deliver.check("two@example.com")
            deliver.check("three@example.com")
        self.assertEqual(resolve.call_count, 1)

    def test_a_refusal_is_cached_too(self):
        with failing(dns.resolver.NXDOMAIN()) as resolve:
            self.assertTrue(deliver.check("a@nope.example").rejects)
            self.assertTrue(deliver.check("b@nope.example").rejects)
        self.assertEqual(resolve.call_count, 1)

    def test_a_refusal_is_cached_for_LESS_time_than_a_pass(self):
        """A domain that has just fixed its DNS should not stay refused all day.
        The asymmetry is the point."""
        with override_settings(
            EMAIL_MX_CACHE_SECONDS=86400, EMAIL_MX_NEGATIVE_CACHE_SECONDS=3600
        ):
            with mock.patch.object(cache, "set") as setter:
                with resolving("mx.example.com."):
                    deliver.check("a@good.example")
                good_ttl = setter.call_args.args[2]
                with failing(dns.resolver.NXDOMAIN()):
                    deliver.check("a@bad.example")
                bad_ttl = setter.call_args.args[2]
        self.assertLess(bad_ttl, good_ttl)

    def test_a_non_answer_is_NOT_cached(self):
        """Caching a timeout turns one bad minute into an hour of it."""
        with failing(dns.exception.Timeout()) as resolve:
            deliver.check("a@example.com")
            deliver.check("b@example.com")
        self.assertEqual(resolve.call_count, 2)

    def test_a_cache_failure_does_not_break_the_check(self):
        with mock.patch.object(cache, "get", side_effect=RuntimeError("redis")):
            with mock.patch.object(cache, "set", side_effect=RuntimeError("redis")):
                with resolving("mx.example.com."):
                    self.assertFalse(deliver.check("a@example.com").rejects)


@override_settings(**ON)
class ImplicitMxTests(TestCase):
    """RFC 5321: with no MX, the A record IS the mail exchanger. Off by default,
    which knowingly refuses a few technically-valid domains — accepted, because
    a bounce costs reputation and the strict default costs a support message."""

    def setUp(self):
        cache.clear()

    def test_off_by_default(self):
        with failing(dns.resolver.NoAnswer()):
            self.assertTrue(deliver.check("a@a-record-only.example").rejects)

    @override_settings(EMAIL_MX_ALLOW_IMPLICIT_MX=True)
    def test_on_it_accepts_an_a_record(self):
        calls = []

        def resolve(domain, rdtype, **kwargs):
            calls.append(rdtype)
            if rdtype == "MX":
                raise dns.resolver.NoAnswer()
            return ["1.2.3.4"]

        with mock.patch.object(dns.resolver, "resolve", side_effect=resolve):
            self.assertFalse(deliver.check("a@a-record-only.example").rejects)
        self.assertEqual(calls, ["MX", "A"])

    @override_settings(EMAIL_MX_ALLOW_IMPLICIT_MX=True)
    def test_on_it_still_refuses_a_domain_with_nothing(self):
        with failing(dns.resolver.NXDOMAIN()):
            self.assertTrue(deliver.check("a@nothing.example").rejects)


class SwitchTests(SimpleTestCase):
    def test_the_older_setting_still_turns_it_off(self):
        """A project that switched the inline signup check off must not silently
        get it back by pulling this in."""
        with override_settings(SIGNUP_EMAIL_MX_CHECK=False):
            self.assertFalse(deliver.enabled())

    def test_it_is_off_in_debug_when_nothing_pins_it(self):
        """The default a boilerplate user gets: local development with fake
        addresses does not need a DNS round trip per signup."""
        from django.conf import settings

        with override_settings(DEBUG=True, SIGNUP_EMAIL_MX_CHECK=True):
            del settings.EMAIL_DELIVERABILITY_CHECK
            self.assertFalse(deliver.enabled())

    def test_it_is_on_outside_debug_when_nothing_pins_it(self):
        from django.conf import settings

        with override_settings(DEBUG=False, SIGNUP_EMAIL_MX_CHECK=True):
            del settings.EMAIL_DELIVERABILITY_CHECK
            self.assertTrue(deliver.enabled())

    def test_the_timeout_is_short_enough_for_a_public_form(self):
        """5s per submission is a denial-of-service assist, which is why the
        inline version's timeout was one of the three defects."""
        self.assertLessEqual(deliver.timeout_seconds(), 3.0)


@override_settings(**ON)
class ValidatorTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_it_raises_the_django_exception_forms_understand(self):
        with failing(dns.resolver.NXDOMAIN()):
            with self.assertRaises(ValidationError):
                deliver.validate("a@nope.example")

    def test_it_returns_the_address_when_it_passes(self):
        with resolving("mx.example.com."):
            self.assertEqual(
                deliver.validate("a@example.com"), "a@example.com"
            )

    def test_a_blank_address_passes(self):
        self.assertEqual(deliver.validate(""), "")


@override_settings(**ON, RECAPTCHA_PUBLIC_KEY="", RECAPTCHA_PRIVATE_KEY="")
class EveryDoorTests(TestCase):
    """The point of the whole exercise: the check used to cover signup ALONE.

    Keys are pinned empty (stacked under ON, not widening it): the signup form
    only runs the deliverability check once the CAPTCHA has passed, so with a
    field present the two signup cases below would fail on a machine that has
    reCAPTCHA keys in its env. See usermodel/tests/test_signup_captcha_gate.py.

    An address can also arrive through an invitation, and it is the same kind of
    liability — an invitation is a piece of mail, so an undeliverable address is
    not an invitation, it is a bounce charged against the SES account.
    """

    def setUp(self):
        cache.clear()

    def test_the_signup_form_refuses_an_undeliverable_address(self):
        from usermodel.forms import UsermodelSignupForm

        with failing(dns.resolver.NXDOMAIN()):
            form = UsermodelSignupForm(
                data={"email": "a@nope.example", "password1": "sufficiently-long-pw"}
            )
            self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_the_signup_form_accepts_a_deliverable_one(self):
        from usermodel.forms import UsermodelSignupForm

        with resolving("mx.example.com."):
            form = UsermodelSignupForm(
                data={"email": "a@example.com", "password1": "sufficiently-long-pw"}
            )
            form.is_valid()
        self.assertNotIn("email", form.errors)

    def test_the_invitation_form_refuses_an_undeliverable_address(self):
        from mainapp.forms.teams import InviteMemberForm
        from mainapp.models import Team

        team = Team.objects.create(name="Acme", slug="acme")
        with failing(dns.resolver.NXDOMAIN()):
            form = InviteMemberForm(
                data={"email": "a@nope.example", "role": "member"}, team=team
            )
            self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_the_invitation_form_accepts_a_deliverable_one(self):
        from mainapp.forms.teams import InviteMemberForm
        from mainapp.models import Team

        team = Team.objects.create(name="Acme", slug="acme")
        with resolving("mx.example.com."):
            form = InviteMemberForm(
                data={"email": "a@example.com", "role": "member"}, team=team
            )
            form.is_valid()
        self.assertNotIn("email", form.errors)

    def test_the_add_email_form_refuses_an_undeliverable_address(self):
        from usermodel.forms import UsermodelAddEmailForm
        from usermodel.models import User

        user = User.objects.create_user(email="owner@example.com", password="pw")
        with failing(dns.resolver.NXDOMAIN()):
            form = UsermodelAddEmailForm(
                user=user, data={"email": "a@nope.example"}
            )
            self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_the_add_email_form_accepts_a_deliverable_one(self):
        from usermodel.forms import UsermodelAddEmailForm
        from usermodel.models import User

        user = User.objects.create_user(email="owner@example.com", password="pw")
        with resolving("mx.example.com."):
            form = UsermodelAddEmailForm(
                user=user, data={"email": "a@example.com"}
            )
            form.is_valid()
        self.assertNotIn("email", form.errors)
