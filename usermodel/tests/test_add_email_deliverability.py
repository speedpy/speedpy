"""The add-email form runs the shared deliverability validator (loose end 51).

``UsermodelAddEmailForm`` is the self-service door on ``/accounts/email/``. It
used to skip the validator every other door calls, so a logged-in user could add
a throwaway address (a dead end — the send-time guard drops the mail) or an
undeliverable one (a hard bounce charged against the SES account). The form now
calls ``email_deliverability.validate`` from ``clean_email``, AFTER
``super().clean_email()`` so allauth's own refusals keep their precedence and the
value validated is the adapter-cleaned one allauth will store.

New file on purpose — NOT ``usermodel/tests/test_existing.py``, which is a
standing merge point in downstream projects.

Same helpers as the captcha-gate tests: ``ON`` turns the DNS half on with a
LocMemCache, ``failing``/``resolving`` mock the resolver. ``cache.clear()`` in
``setUp`` because the per-domain cache is process-wide.
"""

from unittest import mock

import dns.resolver
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from allauth.account.models import EmailAddress

from speedpycom.tests.test_email_deliverability import ON, failing, resolving
from usermodel.adapters import CustomAccountAdapter
from usermodel.forms import UsermodelAddEmailForm
from usermodel.models import User

#: Substring of BLOCKED_EMAIL_MESSAGE — the blocklist refusal.
BLOCKLIST_TEXT = "cannot accept this email address"
#: Substring of NO_MX_MESSAGE — the actionable "you probably mistyped" refusal.
NO_MX_TEXT = "does not appear to accept mail"


@override_settings(**ON)
class AddEmailDeliverabilityFormTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="owner@example.com", password="pw"
        )

    def _errors(self, form):
        return " ".join(str(e) for e in form.errors.get("email", []))

    def test_a_blocklisted_domain_is_refused_without_dns(self):
        """Blocklists first, and even when the DNS half is switched off — a
        blocklist is a policy, not a probe (goal 4)."""
        with override_settings(
            EMAIL_DELIVERABILITY_CHECK=False, SIGNUP_EMAIL_MX_CHECK=False
        ):
            with mock.patch.object(dns.resolver, "resolve") as resolve:
                form = UsermodelAddEmailForm(
                    user=self.user, data={"email": "x@mailinator.com"}
                )
                self.assertFalse(form.is_valid())
            resolve.assert_not_called()
        self.assertIn(BLOCKLIST_TEXT, self._errors(form))

    def test_a_domain_with_no_mx_is_refused_with_the_typo_message(self):
        with failing(dns.resolver.NXDOMAIN()):
            form = UsermodelAddEmailForm(
                user=self.user, data={"email": "x@no-such-domain.example"}
            )
            self.assertFalse(form.is_valid())
        errors = self._errors(form)
        self.assertIn(NO_MX_TEXT, errors)
        self.assertNotIn(BLOCKLIST_TEXT, errors)

    def test_a_deliverable_address_passes(self):
        """The lowercase here comes from allauth's FIELD, so it does not prove
        ``super()`` ran — test 5 does. It does prove a clean address is let in."""
        with resolving("mx.example.com."):
            form = UsermodelAddEmailForm(
                user=self.user, data={"email": "New@Example.com"}
            )
            self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["email"], "new@example.com")

    def test_a_non_answer_fails_open(self):
        """This door inherits the validator's fail-open rule, not a stricter one.
        Assert the resolver WAS consulted, so the test cannot pass vacuously if
        the validator call is ever dropped."""
        with failing(dns.resolver.LifetimeTimeout()) as resolve:
            form = UsermodelAddEmailForm(
                user=self.user, data={"email": "x@timeout.example"}
            )
            self.assertTrue(form.is_valid())
        resolve.assert_called_once()

    def test_allauths_refusal_comes_first_and_costs_no_dns(self):
        """Adding the owner's own login address: allauth refuses it (duplicate)
        from data we already hold, before any DNS and with no deliverability
        message. Proves ``super()`` runs, and runs first (goal 2)."""
        with mock.patch.object(dns.resolver, "resolve") as resolve:
            form = UsermodelAddEmailForm(
                user=self.user, data={"email": self.user.email}
            )
            self.assertFalse(form.is_valid())
        resolve.assert_not_called()
        errors = self._errors(form)
        self.assertIn("already associated with this account", errors)
        self.assertNotIn(NO_MX_TEXT, errors)
        self.assertNotIn(BLOCKLIST_TEXT, errors)

    def test_the_adapters_value_is_what_gets_validated(self):
        """The adapter may rewrite the address; the validator must see the
        rewritten value, not the raw submission (goal 3). A clean submission that
        the adapter turns into a blocklisted address is refused."""
        with resolving("mx.example.com."), mock.patch.object(
            CustomAccountAdapter,
            "clean_email",
            return_value="rewritten@mailinator.com",
        ):
            form = UsermodelAddEmailForm(
                user=self.user, data={"email": "clean@example.com"}
            )
            self.assertFalse(form.is_valid())
        self.assertIn(BLOCKLIST_TEXT, self._errors(form))

    def test_a_clean_address_consults_dns_once(self):
        with resolving("mx.example.com.") as resolve:
            form = UsermodelAddEmailForm(
                user=self.user, data={"email": "fresh@example.com"}
            )
            self.assertTrue(form.is_valid())
        self.assertEqual(resolve.call_count, 1)


@override_settings(**ON)
class AddEmailDeliverabilityViewTests(TestCase):
    """Through the real page. The view branches on the presence of
    ``action_add``; nothing else in the POST is needed.

    ``mail.outbox`` works because Django's test runner swaps ``EMAIL_BACKEND``
    to locmem for the run.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="owner@example.com", password="pw"
        )
        self.client.force_login(self.user)

    def test_a_blocked_address_is_refused_and_no_mail_is_attempted(self):
        resp = self.client.post(
            reverse("account_email"),
            {"action_add": "", "email": "x@mailinator.com"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, BLOCKLIST_TEXT)
        self.assertFalse(
            EmailAddress.objects.filter(email="x@mailinator.com").exists()
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_a_deliverable_address_is_stored_and_mailed(self):
        with resolving("mx.example.com."):
            resp = self.client.post(
                reverse("account_email"),
                {"action_add": "", "email": "second@example.com"},
            )
        self.assertEqual(resp.status_code, 302)
        # Filter by address: dispatch also syncs the owner's login address into
        # EmailAddress, so the table holds two rows after this request.
        self.assertEqual(
            EmailAddress.objects.filter(email="second@example.com").count(), 1
        )
        self.assertEqual(len(mail.outbox), 1)
