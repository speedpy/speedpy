"""Provider-agnostic CAPTCHA verification (speedpycom/services/captcha.py).

The whole point of this module is a distinction the ``django-recaptcha`` form
field does not make, so most of these tests are about which answers refuse a
visitor and which only annotate them. Getting that wrong is expensive in one
direction and useless in the other:

* treating a low score as a refusal throws away real testimonials;
* treating a bad secret as a refusal takes collection down for EVERY visitor
  while looking exactly like a bot flood in the logs;
* treating a reused token as acceptable is the whole bypass.
"""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from speedpycom.services import captcha

KEYS_ON = {"RECAPTCHA_PUBLIC_KEY": "site", "RECAPTCHA_PRIVATE_KEY": "secret"}


def verdict(**kwargs):
    return captcha.ProviderVerdict(**kwargs)


class FakeResponse:
    """Shaped like django_recaptcha.client.RecaptchaResponse."""

    def __init__(self, is_valid=True, error_codes=None, extra_data=None, action=None):
        self.is_valid = is_valid
        self.error_codes = error_codes or []
        self.extra_data = extra_data or {}
        self.action = action


class EnablementTests(SimpleTestCase):
    def test_no_keys_means_the_feature_does_not_exist(self):
        with override_settings(RECAPTCHA_PUBLIC_KEY="", RECAPTCHA_PRIVATE_KEY=""):
            self.assertFalse(captcha.enabled())
            self.assertEqual(captcha.site_key(), "")
            self.assertEqual(
                captcha.verify("anything").outcome, captcha.OUTCOME_DISABLED
            )

    def test_one_key_alone_is_not_enough(self):
        """A half-configured pair must stay off. django-recaptcha would happily
        render a widget against a site key and then fail every verification."""
        with override_settings(RECAPTCHA_PUBLIC_KEY="site", RECAPTCHA_PRIVATE_KEY=""):
            self.assertFalse(captcha.enabled())
        with override_settings(RECAPTCHA_PUBLIC_KEY="", RECAPTCHA_PRIVATE_KEY="secret"):
            self.assertFalse(captcha.enabled())

    @override_settings(**KEYS_ON)
    def test_both_keys_expose_the_site_key(self):
        self.assertTrue(captcha.enabled())
        self.assertEqual(captcha.site_key(), "site")

    @override_settings(**KEYS_ON)
    def test_a_disabled_result_is_not_a_refusal(self):
        """Otherwise every public form would refuse everybody the moment the
        keys were removed from the environment."""
        result = captcha.CaptchaResult(outcome=captcha.OUTCOME_DISABLED)
        self.assertFalse(result.refuses)
        self.assertFalse(result.suspicious)


@override_settings(**KEYS_ON, CAPTCHA_PROVIDER="speedpycom.tests.test_captcha.stub")
class OutcomeTests(SimpleTestCase):
    """Policy: what each provider verdict becomes."""

    def verify(self, provider_verdict, **kwargs):
        global STUB_VERDICT
        STUB_VERDICT = provider_verdict
        return captcha.verify("token", **kwargs)

    def test_a_missing_token_is_absent_and_refuses(self):
        for token in ("", "   ", None):
            with self.subTest(token=token):
                result = captcha.verify(token)
                self.assertEqual(result.outcome, captcha.OUTCOME_ABSENT)
                self.assertTrue(result.refuses)
                self.assertFalse(result.checked)

    def test_a_missing_token_does_not_call_the_provider(self):
        """No network round trip for a request that cannot possibly pass — this
        is the flood case, and it must stay cheap."""
        with mock.patch.object(captcha, "provider") as p:
            captcha.verify("")
            p.assert_not_called()

    def test_a_rejected_token_refuses(self):
        result = self.verify(verdict(ok=False, error_codes=("timeout-or-duplicate",)))
        self.assertEqual(result.outcome, captcha.OUTCOME_FAILED)
        self.assertTrue(result.refuses)
        self.assertTrue(result.checked)

    def test_a_good_score_passes(self):
        result = self.verify(verdict(ok=True, score=0.9))
        self.assertEqual(result.outcome, captcha.OUTCOME_OK)
        self.assertFalse(result.refuses)
        self.assertFalse(result.suspicious)
        self.assertEqual(result.score, 0.9)

    def test_a_low_score_is_flagged_and_NOT_refused(self):
        """The core decision (PROGRESS.md item 17). A false positive here would
        silently discard a real customer's testimonial."""
        result = self.verify(verdict(ok=True, score=0.1))
        self.assertEqual(result.outcome, captcha.OUTCOME_LOW_SCORE)
        self.assertTrue(result.suspicious)
        self.assertFalse(result.refuses)
        self.assertEqual(result.score, 0.1)

    def test_the_score_floor_is_exclusive_at_the_boundary(self):
        self.assertEqual(
            self.verify(verdict(ok=True, score=0.5)).outcome, captcha.OUTCOME_OK
        )
        self.assertEqual(
            self.verify(verdict(ok=True, score=0.49)).outcome,
            captcha.OUTCOME_LOW_SCORE,
        )

    @override_settings(CAPTCHA_MIN_SCORE=0.8)
    def test_the_floor_is_configurable(self):
        self.assertEqual(
            self.verify(verdict(ok=True, score=0.7)).outcome,
            captcha.OUTCOME_LOW_SCORE,
        )

    def test_a_per_call_floor_overrides_the_setting(self):
        self.assertEqual(
            self.verify(verdict(ok=True, score=0.7), floor=0.9).outcome,
            captcha.OUTCOME_LOW_SCORE,
        )

    def test_a_provider_with_no_score_can_never_be_low_score(self):
        """reCAPTCHA v2 and Turnstile answer pass/fail. Comparing None against
        the floor would either crash or flag every single visitor."""
        result = self.verify(verdict(ok=True, score=None))
        self.assertEqual(result.outcome, captcha.OUTCOME_OK)
        self.assertIsNone(result.score)

    def test_an_unavailable_provider_fails_open(self):
        result = self.verify(verdict(unavailable=True))
        self.assertEqual(result.outcome, captcha.OUTCOME_UNAVAILABLE)
        self.assertFalse(result.refuses)
        self.assertFalse(result.checked)

    def test_an_action_mismatch_refuses(self):
        """A token minted for the cheap 'submit' action must not be replayable
        against the expensive one that starts a video transcode."""
        result = self.verify(
            verdict(ok=True, score=0.9, action="submit"),
            expected_action="video_reserve",
        )
        self.assertEqual(result.outcome, captcha.OUTCOME_FAILED)
        self.assertTrue(result.refuses)

    def test_a_matching_action_passes(self):
        result = self.verify(
            verdict(ok=True, score=0.9, action="video_reserve"),
            expected_action="video_reserve",
        )
        self.assertEqual(result.outcome, captcha.OUTCOME_OK)

    def test_no_expected_action_skips_the_check(self):
        result = self.verify(verdict(ok=True, score=0.9, action="whatever"))
        self.assertEqual(result.outcome, captcha.OUTCOME_OK)

    def test_a_provider_that_reports_no_action_is_not_punished(self):
        """Turnstile has no action concept; demanding one would refuse
        everybody the moment somebody swapped provider."""
        result = self.verify(
            verdict(ok=True, score=0.9, action=""), expected_action="submit"
        )
        self.assertEqual(result.outcome, captcha.OUTCOME_OK)

    def test_a_provider_that_raises_is_not_papered_over(self):
        """Where the fail-open boundary sits. A provider is responsible for
        turning ITS transport errors into `unavailable` (recaptcha_v3 does);
        verify() deliberately does not catch, because swallowing a coding error
        as "fail open" would hide a permanently broken provider forever."""

        def boom(token, *, remote_ip=""):
            raise RuntimeError("provider is broken")

        with mock.patch.object(captcha, "provider", return_value=boom):
            with self.assertRaises(RuntimeError):
                captcha.verify("token")


@override_settings(**KEYS_ON)
class RecaptchaProviderTests(SimpleTestCase):
    def submit(self, **response_kwargs):
        with mock.patch(
            "django_recaptcha.client.submit",
            return_value=FakeResponse(**response_kwargs),
        ) as m:
            return captcha.recaptcha_v3("token", remote_ip="1.2.3.4"), m

    def test_it_passes_the_secret_and_the_ip(self):
        _, m = self.submit(extra_data={"score": 0.9})
        m.assert_called_once_with("token", "secret", "1.2.3.4")

    def test_a_valid_response_carries_the_score_and_hostname(self):
        result, _ = self.submit(
            extra_data={"score": 0.7, "hostname": "withfeedback.com"}, action="submit"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.score, 0.7)
        self.assertEqual(result.hostname, "withfeedback.com")
        self.assertEqual(result.action, "submit")

    def test_a_string_score_is_coerced(self):
        """Google documents a number; JSON from a proxy has arrived as a string
        before, and comparing "0.1" < 0.5 raises TypeError."""
        result, _ = self.submit(extra_data={"score": "0.3"})
        self.assertEqual(result.score, 0.3)

    def test_an_unparseable_score_becomes_none_rather_than_crashing(self):
        result, _ = self.submit(extra_data={"score": "high"})
        self.assertIsNone(result.score)
        self.assertTrue(result.ok)

    def test_a_missing_score_is_none(self):
        result, _ = self.submit(extra_data={})
        self.assertIsNone(result.score)

    def test_a_visitor_error_is_a_plain_failure(self):
        result, _ = self.submit(
            is_valid=False, error_codes=["timeout-or-duplicate"]
        )
        self.assertFalse(result.ok)
        self.assertFalse(result.unavailable)

    def test_our_own_bad_secret_fails_OPEN_not_closed(self):
        """The important one. A wrong secret rejects every visitor identically,
        so classifying it as a bad token would silently stop all collection —
        and the logs would read like a bot flood, not a misconfiguration."""
        for code in ("invalid-input-secret", "missing-input-secret", "bad-request"):
            with self.subTest(code=code):
                result, _ = self.submit(is_valid=False, error_codes=[code])
                self.assertTrue(result.unavailable)
                self.assertFalse(result.ok)

    def test_a_site_error_reaching_verify_fails_open(self):
        with mock.patch(
            "django_recaptcha.client.submit",
            return_value=FakeResponse(is_valid=False, error_codes=["invalid-input-secret"]),
        ):
            result = captcha.verify("token")
        self.assertEqual(result.outcome, captcha.OUTCOME_UNAVAILABLE)
        self.assertFalse(result.refuses)

    def test_every_transport_failure_becomes_unavailable(self):
        """urllib raises a different type for DNS, TLS, timeout and a truncated
        body, and none of them should refuse a customer's testimonial."""
        import socket
        import urllib.error

        for exc in (
            urllib.error.URLError("dns"),
            socket.timeout("slow"),
            ValueError("not json"),
            KeyError("success"),
        ):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch("django_recaptcha.client.submit", side_effect=exc):
                    result = captcha.recaptcha_v3("token")
                self.assertTrue(result.unavailable)

    def test_a_long_hostname_and_action_are_truncated(self):
        """Third-party payload straight into our own log lines and JSON columns."""
        result, _ = self.submit(
            extra_data={"score": 0.9, "hostname": "h" * 500}, action="a" * 500
        )
        self.assertEqual(len(result.hostname), 255)
        self.assertEqual(len(result.action), 64)


class MetadataTests(SimpleTestCase):
    def test_metadata_is_small_and_json_safe(self):
        result = captcha.CaptchaResult(
            outcome=captcha.OUTCOME_LOW_SCORE,
            score=0.2,
            provider="recaptcha_v3",
            hostname="withfeedback.com",
        )
        self.assertEqual(
            result.as_metadata(),
            {"outcome": "low_score", "provider": "recaptcha_v3", "score": 0.2},
        )

    def test_the_hostname_and_error_codes_are_not_stored(self):
        """We have no reason to keep a third party's timestamp and hostname on
        a customer's submission row, and storing whatever a provider sends is
        how PII arrives in a JSON column by accident."""
        data = captcha.CaptchaResult(
            outcome=captcha.OUTCOME_FAILED,
            provider="recaptcha_v3",
            hostname="withfeedback.com",
            error_codes=("invalid-input-response",),
        ).as_metadata()
        self.assertNotIn("hostname", data)
        self.assertNotIn("error_codes", data)

    def test_a_scoreless_outcome_omits_the_score_key(self):
        data = captcha.CaptchaResult(
            outcome=captcha.OUTCOME_UNAVAILABLE, provider="recaptcha_v3"
        ).as_metadata()
        self.assertEqual(data, {"outcome": "unavailable", "provider": "recaptcha_v3"})


class ProviderResolutionTests(SimpleTestCase):
    @override_settings(**KEYS_ON, CAPTCHA_PROVIDER="speedpycom.tests.test_captcha.stub")
    def test_the_provider_is_a_setting(self):
        global STUB_VERDICT
        STUB_VERDICT = verdict(ok=True, score=0.9)
        self.assertEqual(captcha.verify("t").outcome, captcha.OUTCOME_OK)
        self.assertEqual(captcha.verify("t").provider, "stub")

    @override_settings(**KEYS_ON)
    def test_changing_the_setting_clears_the_cache(self):
        """Resolved once per process for speed; a stale cache would make the
        setting a lie in tests and after a hot reload."""
        with override_settings(CAPTCHA_PROVIDER="speedpycom.tests.test_captcha.stub"):
            self.assertIs(captcha.provider(), stub)
        with override_settings(
            CAPTCHA_PROVIDER="speedpycom.services.captcha.recaptcha_v3"
        ):
            self.assertIs(captcha.provider(), captcha.recaptcha_v3)


STUB_VERDICT = captcha.ProviderVerdict(ok=True, score=0.9)


def stub(token, *, remote_ip=""):
    return STUB_VERDICT
