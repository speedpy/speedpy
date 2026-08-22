"""Tests for EMAIL_PROVIDER selection and the post_office backend mapping."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from project.email_providers import (
    EMAIL_PROVIDER_BACKENDS,
    resolve_email_backend,
)


class EmailProviderResolutionTests(SimpleTestCase):
    def test_each_valid_provider_maps_to_expected_backend(self):
        expected = {
            "console": "django.core.mail.backends.console.EmailBackend",
            "smtp": "django.core.mail.backends.smtp.EmailBackend",
            "ses": "anymail.backends.amazon_ses.EmailBackend",
            "mailgun": "anymail.backends.mailgun.EmailBackend",
            "sendgrid": "anymail.backends.sendgrid.EmailBackend",
            "postmark": "anymail.backends.postmark.EmailBackend",
            "resend": "anymail.backends.resend.EmailBackend",
        }
        self.assertEqual(EMAIL_PROVIDER_BACKENDS, expected)
        for provider, backend in expected.items():
            self.assertEqual(resolve_email_backend(provider), backend)

    def test_invalid_provider_raises_with_valid_names(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            resolve_email_backend("nope")
        message = str(ctx.exception)
        self.assertIn("nope", message)
        for provider in EMAIL_PROVIDER_BACKENDS:
            self.assertIn(provider, message)

    def test_post_office_delegates_through_the_suppression_guard(self):
        # post_office's backend is now the suppression guard, which wraps the
        # backend EMAIL_PROVIDER selects. Wrapping there rather than at each
        # call site is what makes an address that hard-bounced un-sendable from
        # allauth, team invitations and any third-party package alike.
        self.assertEqual(
            settings.POST_OFFICE["BACKENDS"]["default"],
            "speedpycom.email_backends.SuppressionAwareEmailBackend",
        )

    def test_default_settings_use_console_backend(self):
        # No EMAIL_PROVIDER set in the test environment -> console default.
        # Asserted through the guard's own resolution rather than through
        # POST_OFFICE, since the guard is what post_office now points at.
        from speedpycom.email_backends import SuppressionAwareEmailBackend

        self.assertEqual(
            SuppressionAwareEmailBackend._inner_path(),
            "django.core.mail.backends.console.EmailBackend",
        )

    def test_anymail_credentials_have_placeholder_defaults(self):
        # App boots without real provider keys configured.
        self.assertEqual(settings.ANYMAIL["SENDGRID_API_KEY"], "change_me")
        self.assertEqual(settings.ANYMAIL["POSTMARK_SERVER_TOKEN"], "change_me")
        self.assertEqual(settings.ANYMAIL["RESEND_API_KEY"], "change_me")

    def test_ses_omits_aws_keys_when_unset_for_credential_chain(self):
        # With no AWS_SES_* keys in the env, only region is passed so boto3 falls
        # back to its standard credential chain (IAM role, ~/.aws/credentials).
        ses_params = settings.ANYMAIL["AMAZON_SES_CLIENT_PARAMS"]
        self.assertIn("region_name", ses_params)
        self.assertNotIn("aws_access_key_id", ses_params)
        self.assertNotIn("aws_secret_access_key", ses_params)
