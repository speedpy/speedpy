"""Signup form: the blocklist / deliverability verdict waits for the CAPTCHA.

Loose end: a POST with no reCAPTCHA token, or a bad one, still learned whether a
domain was refused. Django's ``full_clean`` runs EVERY field cleaner and collects
EVERY field error before ``clean()`` runs, so the old ``clean_email`` answered
"is this domain blocked?" to anyone — one domain per request rebuilds the whole
blocklist. The check now runs from ``clean()`` and only when ``captcha_passed()``.

Do NOT move these into ``usermodel/tests/test_existing.py`` — that file is a
standing merge point in downstream projects. New file on purpose.

The POST key for the token is the Django FIELD name ``captcha``, NOT
``g-recaptcha-response``: ``ReCaptchaV3.value_from_datadict`` returns
``data.get(name)``. Post the wrong key and the field looks *missing*, the
``submit`` mock is never reached, and a "passed CAPTCHA" test passes vacuously —
so every token-bearing test asserts the mock was called.
"""

from unittest import mock

import dns.resolver
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from speedpycom.services import email_domains
from speedpycom.tests.test_email_deliverability import ON, failing
from usermodel.forms import UsermodelSignupForm
from usermodel.models import User

KEYS_ON = {"RECAPTCHA_PUBLIC_KEY": "pub", "RECAPTCHA_PRIVATE_KEY": "priv"}

#: On the bundled throwaway list; refused by the blocklist half, no DNS needed.
BLOCKED = "someone@mailinator.com"
#: On no list; DNS is off under test, so the validator calls this one "fine".
CLEAN = "someone@example.com"
PASSWORD = "sup3r-Secret-pass!"

BLOCKLIST_TEXT = "cannot accept this email address"
CAPTCHA_REQUIRED = "This field is required."


class FakeRecaptcha:
    """Shaped like ``django_recaptcha.client.RecaptchaResponse``.

    ``action`` must be ``None``: the signup widget is ``ReCaptchaV3()`` with no
    action, and ``ReCaptchaField.validate`` refuses when
    ``check.action != widget.action``. A passing fake is
    ``is_valid=True, action=None, score=0.9`` (threshold is
    ``RECAPTCHA_REQUIRED_SCORE``, default 0.5).
    """

    def __init__(self, is_valid=True, error_codes=(), action=None, score=0.9):
        self.is_valid = is_valid
        self.error_codes = list(error_codes)
        self.action = action
        self.extra_data = {"score": score}


def _submit(**kw):
    return mock.patch(
        "django_recaptcha.client.submit", return_value=FakeRecaptcha(**kw)
    )


def _body(email, *, token=True):
    body = {"email": email, "password1": PASSWORD, "tos": "on", "dpa": "on"}
    if token:
        body["captcha"] = "token"
    return body


@override_settings(**KEYS_ON)
class FailedCaptchaWithholdsTheVerdict(TestCase):
    """A CAPTCHA that did not pass must reveal nothing from the email validator."""

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_a_failed_captcha_withholds_the_blocklist_verdict(self):
        with _submit(is_valid=False) as submit:
            response = self.client.post("/accounts/signup/", _body(BLOCKED))
        submit.assert_called()  # never vacuous: the token really reached the field
        self.assertEqual(response.status_code, 200)
        # The leak, directly: the blocklist verdict must not reach the page.
        self.assertNotContains(response, BLOCKLIST_TEXT)
        # The oracle is the presence of an ``email`` error, not its wording; the
        # captcha error is what actually stopped the form. (The hidden reCAPTCHA
        # field's own error is not rendered into the body by the crispy field
        # template, so assert it on ``form.errors``, which is the reliable
        # signal — see plan §1.)
        errors = response.context["form"].errors
        self.assertNotIn("email", errors)
        self.assertIn("captcha", errors)

    def test_a_missing_token_withholds_the_verdict(self):
        # No token in the POST: the captcha field is required, so it errors
        # before submit() is ever consulted (no mock needed).
        response = self.client.post("/accounts/signup/", _body(BLOCKED, token=False))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, BLOCKLIST_TEXT)
        errors = response.context["form"].errors
        self.assertNotIn("email", errors)
        self.assertEqual(errors["captcha"], [CAPTCHA_REQUIRED])

    def test_a_failed_captcha_never_consults_the_validator(self):
        # Also the "no DNS" proof: the validator is not called at all.
        with _submit(is_valid=False) as submit, mock.patch(
            "speedpycom.services.email_deliverability.validate"
        ) as validate:
            self.client.post("/accounts/signup/", _body(BLOCKED))
        submit.assert_called()
        validate.assert_not_called()

    def test_blocked_and_clean_domains_are_indistinguishable_when_the_captcha_fails(self):
        # The direct oracle test: the two responses must be byte-identical in
        # what they say about the email.
        with _submit(is_valid=False) as submit_blocked:
            blocked = self.client.post("/accounts/signup/", _body(BLOCKED))
        with _submit(is_valid=False) as submit_clean:
            clean = self.client.post("/accounts/signup/", _body(CLEAN))
        # Not vacuous: the token really reached the field in both requests.
        submit_blocked.assert_called()
        submit_clean.assert_called()
        self.assertEqual(
            blocked.context["form"].errors, clean.context["form"].errors
        )

    def test_an_existing_address_with_a_failed_captcha_creates_nothing_and_sends_nothing(self):
        # allauth's account_already_exists flag is set in clean_email, but
        # try_save() and the "account exists" mail are only reached from
        # form_valid(); an invalid form reaches neither.
        User.objects.create_user(email="taken@example.com", password=PASSWORD)
        before = User.objects.count()
        with _submit(is_valid=False) as submit:
            response = self.client.post(
                "/accounts/signup/", _body("taken@example.com")
            )
        submit.assert_called()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("Location"))
        errors = response.context["form"].errors
        self.assertIn("captcha", errors)
        self.assertNotIn("email", errors)
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(**KEYS_ON)
class PassedCaptchaStillRefuses(TestCase):
    """When the CAPTCHA passes, behaviour is exactly today's."""

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_a_passed_captcha_still_refuses_a_blocked_domain(self):
        with _submit(is_valid=True) as submit:
            response = self.client.post("/accounts/signup/", _body(BLOCKED))
        submit.assert_called()
        self.assertContains(response, BLOCKLIST_TEXT)
        errors = response.context["form"].errors
        self.assertIn("email", errors)
        self.assertNotIn("captcha", errors)


@override_settings(**{**ON, **KEYS_ON})
class PassedCaptchaStillRefusesUndeliverable(TestCase):
    """The deliverability half (not just the blocklist) is gated too.

    ``ON`` pins both ``EMAIL_DELIVERABILITY_CHECK`` and the legacy
    ``SIGNUP_EMAIL_MX_CHECK`` (either off disables DNS) and swaps in a LocMem
    cache. It must sit on the CLASS, not the method: ``setUp`` runs before a
    method-level override activates, so a ``cache.clear()`` there would clear the
    wrong backend. ``nope.example`` is on no blocklist, so a real refusal proves
    the resolver was actually consulted.
    """

    def setUp(self):
        cache.clear()  # a cached verdict would bypass the resolver mock

    def test_a_passed_captcha_still_refuses_an_undeliverable_domain(self):
        with _submit(is_valid=True) as submit, failing(
            dns.resolver.NXDOMAIN()
        ) as resolve:
            response = self.client.post(
                "/accounts/signup/", _body("a@nope.example")
            )
        submit.assert_called()
        resolve.assert_called()  # not short-circuited by blocklist or cache
        errors = response.context["form"].errors
        self.assertIn("email", errors)
        self.assertIn("typos", " ".join(errors["email"]).lower())
        self.assertNotIn("captcha", errors)


@override_settings(**KEYS_ON)
class FormLevelPlacementTests(TestCase):
    """No HTTP: pin the clean() placement independent of the view."""

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    def test_a_failed_captcha_leaves_no_email_error_on_the_form(self):
        with _submit(is_valid=False) as submit:
            form = UsermodelSignupForm(data=_body(BLOCKED))
            self.assertFalse(form.is_valid())
        submit.assert_called()
        self.assertNotIn("email", form.errors)
        self.assertIn("captcha", form.errors)


class RefusedAddressNeverReachesPasswordValidators(TestCase):
    """Keys OFF (so the verdict IS given): a refused address must be out of
    cleaned_data before allauth's SignupForm.clean() builds the dummy user, or
    UserAttributeSimilarityValidator would add a password1 error that does not
    exist today. This pins the ordering in clean() — the wrong order fails it.
    """

    def setUp(self):
        email_domains.clear_cache()
        self.addCleanup(email_domains.clear_cache)

    @override_settings(RECAPTCHA_PUBLIC_KEY="", RECAPTCHA_PRIVATE_KEY="")
    def test_a_refused_address_never_reaches_the_password_validators(self):
        form = UsermodelSignupForm(
            data={
                "email": BLOCKED,
                "password1": BLOCKED,  # identical to the email on purpose
                "tos": "on",
                "dpa": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertNotIn("captcha", form.fields)
        self.assertIn("email", form.errors)
        self.assertNotIn("password1", form.errors)
