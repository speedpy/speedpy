"""SES event tracking, SNS verification and suppression (spec §3.20).

The signature tests use a real self-signed RSA key so the crypto path is
genuinely exercised rather than mocked — a mocked verifier proves nothing about
the one function whose failure mode is "accepts forged bounces".
"""

import base64
import datetime
import json
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.urls import reverse

from speedpycom.models import EmailEvent, SuppressedEmail
from speedpycom.services import email_events, sns

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
TOPIC = "arn:aws:sns:eu-central-1:456408556035:withfeedback-ses-events"
PEM_PATH = "/SimpleNotificationService-abc.pem"
CERT_URL = f"https://sns.eu-central-1.amazonaws.com{PEM_PATH}"


def build_certificate(
    key,
    issuer_cn="Amazon RSA 2048 M01",
    not_before_days=-1,
    not_after_days=30,
):
    """Build a certificate for tests. Defaults look like a genuine SNS one."""
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
        )
        .issuer_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)])
        )
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + datetime.timedelta(days=not_before_days))
        .not_valid_after(now + datetime.timedelta(days=not_after_days))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def make_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    return key, pem


def sign_envelope(envelope, key, version="1"):
    """Sign an SNS envelope the way AWS does, so verification is real."""
    envelope = dict(envelope, SignatureVersion=version, SigningCertURL=CERT_URL)
    signed = sns.canonical_string(envelope)
    hash_cls = sns.HASHES[version]
    signature = key.sign(signed, padding.PKCS1v15(), hash_cls())
    envelope["Signature"] = base64.b64encode(signature).decode()
    return envelope


def notification(message_dict, message_id="sns-1"):
    return {
        "Type": "Notification",
        "MessageId": message_id,
        "TopicArn": TOPIC,
        "Message": json.dumps(message_dict),
        "Timestamp": "2026-08-21T10:00:00.000Z",
    }


def bounce_payload(recipient="bad@example.com", bounce_type="Permanent"):
    return {
        "notificationType": "Bounce",
        "mail": {
            "messageId": "ses-msg-1",
            "timestamp": "2026-08-21T09:59:00.000Z",
            "destination": [recipient],
        },
        "bounce": {
            "bounceType": bounce_type,
            "bounceSubType": "General",
            "bouncedRecipients": [
                {"emailAddress": recipient, "diagnosticCode": "smtp; 550 no such user"}
            ],
        },
    }


@override_settings(CACHES=LOCMEM_CACHE)
class SNSVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.key, self.pem = make_keypair()

    def verify(self, envelope):
        with mock.patch.object(sns, "fetch_certificate") as fetch:
            from cryptography.x509 import load_pem_x509_certificate

            fetch.return_value = load_pem_x509_certificate(self.pem)
            return sns.verify_message(envelope)

    def test_a_genuine_signature_verifies(self):
        envelope = sign_envelope(notification(bounce_payload()), self.key)
        self.assertIsNone(self.verify(envelope))

    def test_sha256_version_two_verifies(self):
        envelope = sign_envelope(notification(bounce_payload()), self.key, version="2")
        self.assertIsNone(self.verify(envelope))

    def test_a_tampered_message_is_refused(self):
        """The whole point: change the payload, the signature must stop matching."""
        envelope = sign_envelope(notification(bounce_payload()), self.key)
        envelope["Message"] = json.dumps(bounce_payload("victim@example.com"))
        with self.assertRaises(sns.SNSVerificationError):
            self.verify(envelope)

    def test_a_signature_from_another_key_is_refused(self):
        other_key, _ = make_keypair()
        envelope = sign_envelope(notification(bounce_payload()), other_key)
        with self.assertRaises(sns.SNSVerificationError):
            self.verify(envelope)

    def test_unknown_signature_version_is_refused_not_defaulted(self):
        envelope = sign_envelope(notification(bounce_payload()), self.key)
        envelope["SignatureVersion"] = "9"
        with self.assertRaises(sns.SNSVerificationError):
            self.verify(envelope)

    def test_missing_signature_is_refused(self):
        envelope = notification(bounce_payload())
        envelope["SignatureVersion"] = "1"
        with self.assertRaises(sns.SNSVerificationError):
            self.verify(envelope)

    def test_unsupported_message_type_is_refused(self):
        with self.assertRaises(sns.SNSVerificationError):
            sns.canonical_string({"Type": "SomethingElse"})

    def test_canonical_string_omits_absent_optional_fields(self):
        """Subject is optional; including it as empty breaks the signature."""
        without = sns.canonical_string(notification(bounce_payload()))
        self.assertNotIn(b"Subject", without)
        with_subject = sns.canonical_string(
            dict(notification(bounce_payload()), Subject="hi")
        )
        self.assertIn(b"Subject\nhi\n", with_subject)


class CertificateURLAllowlistTests(TestCase):
    """The attacker-supplied field. Getting this wrong makes the signature
    check vacuous: sign your own payload, host your own cert, done."""

    def test_aws_sns_hosts_are_accepted(self):
        for host in (
            f"https://sns.eu-central-1.amazonaws.com{PEM_PATH}",
            f"https://sns.us-east-1.amazonaws.com{PEM_PATH}",
            f"https://sns.cn-north-1.amazonaws.com.cn{PEM_PATH}",
            f"https://sns.eu-central-1.amazonaws.com:443{PEM_PATH}",
        ):
            with self.subTest(url=host):
                self.assertEqual(sns._validate_cert_url(host), host)

    def test_lookalike_and_hostile_hosts_are_refused(self):
        for url in (
            f"https://sns.eu-central-1.amazonaws.com.evil.tld{PEM_PATH}",
            f"https://evil.tld/sns.eu-central-1.amazonaws.com{PEM_PATH}",
            f"https://sns.amazonaws.com.evil{PEM_PATH}",
            f"http://sns.eu-central-1.amazonaws.com{PEM_PATH}",  # not https
            "https://169.254.169.254/latest/meta-data/",          # SSRF target
            f"https://localhost{PEM_PATH}",
            "",
        ):
            with self.subTest(url=url):
                with self.assertRaises(sns.SNSVerificationError):
                    sns._validate_cert_url(url)

    def test_an_allowed_host_with_a_hostile_path_is_refused(self):
        """The host allowlist alone leaves two holes: an arbitrary path is still
        a request we can be made to send, and it lets an attacker choose the
        cache key a fetched certificate is stored under."""
        for url in (
            "https://sns.eu-central-1.amazonaws.com/",
            "https://sns.eu-central-1.amazonaws.com/x.pem",
            "https://sns.eu-central-1.amazonaws.com/latest/meta-data/",
            f"https://sns.eu-central-1.amazonaws.com{PEM_PATH}/../evil.pem",
            f"https://sns.eu-central-1.amazonaws.com{PEM_PATH}?a=1",
        ):
            with self.subTest(url=url):
                with self.assertRaises(sns.SNSVerificationError):
                    sns._validate_cert_url(url)

    def test_a_non_standard_port_is_refused(self):
        with self.assertRaises(sns.SNSVerificationError):
            sns._validate_cert_url(
                f"https://sns.eu-central-1.amazonaws.com:8443{PEM_PATH}"
            )

    def test_embedded_credentials_are_refused(self):
        with self.assertRaises(sns.SNSVerificationError):
            sns._validate_cert_url(
                f"https://user:pw@sns.eu-central-1.amazonaws.com{PEM_PATH}"
            )


class SubscribeURLAllowlistTests(TestCase):
    """The URL the confirmation handler actually fetches.

    This is the trap the first version fell into: SigningCertURL had already
    been validated by then, which made the handler feel safe. SubscribeURL is a
    different URL from the same message, and nothing checked it.
    """

    def test_a_real_confirmation_url_is_accepted(self):
        url = (
            "https://sns.eu-central-1.amazonaws.com/"
            "?Action=ConfirmSubscription&TopicArn=x&Token=y"
        )
        self.assertEqual(sns.validate_subscribe_url(url), url)

    def test_the_metadata_service_is_refused(self):
        for url in (
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "https://169.254.169.254/?Action=ConfirmSubscription",
            "http://127.0.0.1:8000/?Action=ConfirmSubscription",
            "http://[::1]/?Action=ConfirmSubscription",
            "https://evil.example/?Action=ConfirmSubscription",
        ):
            with self.subTest(url=url):
                with self.assertRaises(sns.SNSVerificationError):
                    sns.validate_subscribe_url(url)

    def test_an_sns_host_doing_something_else_is_refused(self):
        """An allowed host is not a licence to call any action on it."""
        with self.assertRaises(sns.SNSVerificationError):
            sns.validate_subscribe_url(
                "https://sns.eu-central-1.amazonaws.com/?Action=Publish"
            )


class EventRecordingTests(TestCase):
    def test_a_permanent_bounce_records_and_suppresses(self):
        created = email_events.record_ses_notification("sns-1", bounce_payload())
        self.assertEqual(len(created), 1)
        event = created[0]
        self.assertEqual(event.event_type, EmailEvent.Type.BOUNCE)
        self.assertEqual(event.bounce_type, EmailEvent.BounceType.PERMANENT)
        self.assertIn("550", event.diagnostic)
        self.assertTrue(email_events.is_suppressed("bad@example.com"))

    def test_a_transient_bounce_records_but_NEVER_suppresses(self):
        """A full mailbox is not a reason to stop writing to somebody forever."""
        email_events.record_ses_notification(
            "sns-2", bounce_payload("full@example.com", bounce_type="Transient")
        )
        self.assertTrue(
            EmailEvent.objects.filter(recipient="full@example.com").exists()
        )
        self.assertFalse(email_events.is_suppressed("full@example.com"))

    def test_a_complaint_always_suppresses(self):
        payload = {
            "notificationType": "Complaint",
            "mail": {"messageId": "m2", "destination": ["angry@example.com"]},
            "complaint": {
                "complainedRecipients": [{"emailAddress": "angry@example.com"}],
                "complaintFeedbackType": "abuse",
            },
        }
        email_events.record_ses_notification("sns-3", payload)
        self.assertTrue(email_events.is_suppressed("angry@example.com"))

    def test_delivery_and_send_do_not_suppress(self):
        for kind, key in (("Delivery", "delivery"), ("Send", "send")):
            payload = {
                "notificationType": kind,
                "mail": {"messageId": "m", "destination": ["ok@example.com"]},
                key: {"recipients": ["ok@example.com"]},
            }
            email_events.record_ses_notification(f"sns-{kind}", payload)
        self.assertFalse(email_events.is_suppressed("ok@example.com"))

    def test_replayed_notification_is_idempotent(self):
        """SNS delivers at least once."""
        email_events.record_ses_notification("sns-dup", bounce_payload())
        again = email_events.record_ses_notification("sns-dup", bounce_payload())
        self.assertEqual(again, [])
        self.assertEqual(EmailEvent.objects.count(), 1)

    def test_multiple_recipients_each_get_an_event(self):
        payload = bounce_payload()
        payload["bounce"]["bouncedRecipients"] = [
            {"emailAddress": "a@example.com", "diagnosticCode": "550"},
            {"emailAddress": "b@example.com", "diagnosticCode": "550"},
        ]
        created = email_events.record_ses_notification("sns-multi", payload)
        self.assertEqual(len(created), 2)
        self.assertTrue(email_events.is_suppressed("b@example.com"))

    def test_recipient_case_is_normalized(self):
        payload = bounce_payload("MiXeD@Example.COM")
        email_events.record_ses_notification("sns-case", payload)
        self.assertTrue(email_events.is_suppressed("mixed@example.com"))
        self.assertTrue(email_events.is_suppressed("MIXED@EXAMPLE.COM"))

    def test_an_unknown_event_type_is_stored_not_dropped(self):
        payload = {
            "eventType": "SomethingNew",
            "mail": {"messageId": "m3", "destination": ["x@example.com"]},
        }
        created = email_events.record_ses_notification("sns-unknown", payload)
        self.assertEqual(created[0].event_type, EmailEvent.Type.OTHER)



class SuppressionListTests(TestCase):
    def test_suppress_is_idempotent(self):
        email_events.suppress("x@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        email_events.suppress("x@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        self.assertEqual(SuppressedEmail.objects.count(), 1)

    def test_release_lets_an_address_through_again(self):
        email_events.suppress("y@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        self.assertTrue(email_events.release("y@example.com"))
        self.assertFalse(email_events.is_suppressed("y@example.com"))

    def test_a_fresh_bounce_overrides_a_manual_release(self):
        """New evidence beats an operator's optimism."""
        email_events.suppress("z@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        email_events.release("z@example.com")
        email_events.record_ses_notification("sns-again", bounce_payload("z@example.com"))
        self.assertTrue(email_events.is_suppressed("z@example.com"))

    def test_suppressed_among_is_one_query_for_many(self):
        email_events.suppress("a@example.com", SuppressedEmail.Reason.COMPLAINT)
        with self.assertNumQueries(1):
            found = email_events.suppressed_among(
                ["a@example.com", "b@example.com", "A@EXAMPLE.COM"]
            )
        self.assertEqual(found, {"a@example.com"})


@override_settings(CACHES=LOCMEM_CACHE, SES_EVENT_TOPIC_ARN=TOPIC)
class WebhookEndpointTests(TestCase):
    """Response codes matter: SNS retries non-2xx and eventually disables an
    endpoint that keeps failing."""

    def setUp(self):
        cache.clear()
        self.key, self.pem = make_keypair()
        self.url = reverse("ses_events")

    def post(self, envelope):
        from cryptography.x509 import load_pem_x509_certificate

        with mock.patch.object(
            sns, "fetch_certificate",
            return_value=load_pem_x509_certificate(self.pem),
        ):
            return self.client.post(
                self.url, data=json.dumps(envelope), content_type="application/json"
            )

    def test_a_signed_bounce_is_accepted_and_suppresses(self):
        envelope = sign_envelope(notification(bounce_payload()), self.key)
        response = self.post(envelope)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(email_events.is_suppressed("bad@example.com"))

    def test_an_unsigned_post_is_403_not_500(self):
        """A forged message will never verify, so retrying it forever is
        pointless — 403 tells SNS to stop."""
        response = self.post(notification(bounce_payload()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(EmailEvent.objects.count(), 0)

    def test_a_tampered_message_is_403_and_records_nothing(self):
        envelope = sign_envelope(notification(bounce_payload()), self.key)
        envelope["Message"] = json.dumps(bounce_payload("victim@example.com"))
        self.assertEqual(self.post(envelope).status_code, 403)
        self.assertFalse(email_events.is_suppressed("victim@example.com"))

    def test_a_foreign_topic_is_refused_even_when_validly_signed(self):
        """Anyone can create an SNS topic and point it at us; their messages
        carry a real AWS signature."""
        envelope = notification(bounce_payload())
        envelope["TopicArn"] = "arn:aws:sns:eu-central-1:999:someone-elses-topic"
        envelope = sign_envelope(envelope, self.key)
        self.assertEqual(self.post(envelope).status_code, 403)
        self.assertEqual(EmailEvent.objects.count(), 0)

    def test_malformed_json_is_400(self):
        response = self.client.post(
            self.url, data="{not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_body_is_413(self):
        response = self.client.post(
            self.url, data="x" * (300 * 1024), content_type="application/json"
        )
        self.assertEqual(response.status_code, 413)

    def test_a_replayed_notification_still_returns_200(self):
        """Not an error — SNS delivers at least once, and a non-2xx would make
        it retry a message we already handled."""
        envelope = sign_envelope(notification(bounce_payload()), self.key)
        self.assertEqual(self.post(envelope).status_code, 200)
        self.assertEqual(self.post(envelope).status_code, 200)
        self.assertEqual(EmailEvent.objects.count(), 1)

    def test_subscription_confirmation_fetches_the_subscribe_url(self):
        envelope = sign_envelope(
            {
                "Type": "SubscriptionConfirmation",
                "MessageId": "sub-1",
                "TopicArn": TOPIC,
                "Token": "tok",
                "Message": "please confirm",
                "SubscribeURL": (
                    "https://sns.eu-central-1.amazonaws.com/"
                    "?Action=ConfirmSubscription&TopicArn=x&Token=y"
                ),
                "Timestamp": "2026-08-21T10:00:00.000Z",
            },
            self.key,
        )
        with mock.patch("requests.get") as get:
            get.return_value = mock.Mock(status_code=200, raw=mock.Mock())
            self.assertEqual(self.post(envelope).status_code, 200)
        get.assert_called_once()
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

    def test_an_unsigned_subscription_confirmation_is_never_confirmed(self):
        """Otherwise anyone could make us subscribe to their topic."""
        envelope = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "sub-2",
            "TopicArn": TOPIC,
            "Token": "tok",
            "Message": "please confirm",
            "SubscribeURL": "https://evil.example/confirm",
            "Timestamp": "2026-08-21T10:00:00.000Z",
        }
        with mock.patch("requests.get") as get:
            self.assertEqual(self.post(envelope).status_code, 403)
        get.assert_not_called()

    def test_unparseable_inner_message_is_accepted_not_retried(self):
        envelope = notification({})
        envelope["Message"] = "this is not json"
        envelope = sign_envelope(envelope, self.key)
        self.assertEqual(self.post(envelope).status_code, 200)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class SuppressionBackendTests(TestCase):
    """The guard that actually prevents the bounce loop."""

    def setUp(self):
        from django.core import mail

        mail.outbox = []

    def send(self, to, subject="hello"):
        from django.core.mail import EmailMessage

        from speedpycom.email_backends import SuppressionAwareEmailBackend

        backend = SuppressionAwareEmailBackend()
        message = EmailMessage(subject, "body", "from@withfeedback.com", to)
        return backend.send_messages([message]), message

    def test_a_clean_address_is_sent(self):
        sent, _ = self.send(["fine@example.com"])
        self.assertEqual(sent, 1)

    def test_a_suppressed_address_is_never_attempted(self):
        email_events.suppress("bad@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        with mock.patch.object(
            __import__("django.core.mail.backends.locmem", fromlist=["EmailBackend"]).EmailBackend,
            "send_messages",
        ) as inner:
            self.send(["bad@example.com"])
        inner.assert_not_called()

    def test_a_mixed_message_keeps_the_good_recipients(self):
        email_events.suppress("bad@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        sent, message = self.send(["bad@example.com", "good@example.com"])
        self.assertEqual(message.to, ["good@example.com"])
        self.assertEqual(sent, 1)

    def test_case_differences_do_not_slip_past(self):
        email_events.suppress("bad@example.com", SuppressedEmail.Reason.COMPLAINT)
        _, message = self.send(["BAD@Example.com", "ok@example.com"])
        self.assertEqual(message.to, ["ok@example.com"])

    def test_cc_and_bcc_are_filtered_too(self):
        from django.core.mail import EmailMessage

        from speedpycom.email_backends import SuppressionAwareEmailBackend

        email_events.suppress("bad@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        message = EmailMessage(
            "s", "b", "from@withfeedback.com", ["ok@example.com"],
            cc=["bad@example.com"], bcc=["bad@example.com", "other@example.com"],
        )
        SuppressionAwareEmailBackend().send_messages([message])
        self.assertEqual(message.cc, [])
        self.assertEqual(message.bcc, ["other@example.com"])

    def test_a_released_address_is_sendable_again(self):
        email_events.suppress("z@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        email_events.release("z@example.com")
        sent, message = self.send(["z@example.com"])
        self.assertEqual(message.to, ["z@example.com"])
        self.assertEqual(sent, 1)

    def test_the_guard_is_installed_as_post_offices_backend(self):
        from django.conf import settings

        self.assertEqual(
            settings.POST_OFFICE["BACKENDS"]["default"],
            "speedpycom.email_backends.SuppressionAwareEmailBackend",
        )


class ConfigurationSetWiringTests(TestCase):
    """The silent failure mode: without a configuration set attached to the
    send, SES fires no events, mail still sends, and nothing complains."""

    def test_unset_resolves_to_None_not_empty_string(self):
        """Anymail tests `is not None`, so "" would send
        ConfigurationSetName="" and SES would reject every message."""
        from django.conf import settings

        if not settings.AWS_SES_CONFIGURATION_SET:
            self.assertIsNone(settings.ANYMAIL["AMAZON_SES_CONFIGURATION_SET_NAME"])

    @override_settings(AWS_SES_CONFIGURATION_SET="withfeedback-events")
    def test_the_setting_name_is_the_one_anymail_reads(self):
        """Guards against renaming it to something plausible that Anymail
        ignores — which would look configured and send no events."""
        from anymail.backends.amazon_ses import EmailBackend

        with override_settings(
            ANYMAIL={"AMAZON_SES_CONFIGURATION_SET_NAME": "withfeedback-events"}
        ):
            backend = EmailBackend()
            self.assertEqual(backend.configuration_set_name, "withfeedback-events")


class CertificateAuthenticationTests(TestCase):
    """Parsing a PEM proves nothing.

    A self-signed certificate verifies a signature made with its own key
    perfectly — the attacker made both. So the certificate has to be checked,
    not merely loaded. These tests cover the checks that stand between an
    allowlisted URL and a trusted public key.
    """

    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def test_an_amazon_issued_current_certificate_is_accepted(self):
        pem = build_certificate(self.key)
        self.assertIsNotNone(sns._authenticate_certificate(pem))

    def test_a_self_signed_certificate_is_refused(self):
        """The attack this exists to stop: host your own cert, sign your own
        payload, and the maths checks out."""
        pem = build_certificate(self.key, issuer_cn="Totally Legit CA")
        with self.assertRaises(sns.SNSVerificationError):
            sns._authenticate_certificate(pem)

    def test_an_expired_certificate_is_refused(self):
        pem = build_certificate(self.key, not_before_days=-60, not_after_days=-30)
        with self.assertRaises(sns.SNSVerificationError):
            sns._authenticate_certificate(pem)

    def test_a_not_yet_valid_certificate_is_refused(self):
        pem = build_certificate(self.key, not_before_days=10, not_after_days=40)
        with self.assertRaises(sns.SNSVerificationError):
            sns._authenticate_certificate(pem)

    def test_the_fetch_does_not_follow_redirects(self):
        """Only the URL we were GIVEN was allowlisted. One open redirect on an
        AWS host would otherwise hand over the key we trust."""
        cache.delete(f"sns:cert:{CERT_URL}")
        pem = build_certificate(self.key)
        raw = mock.Mock()
        raw.read.return_value = pem
        with mock.patch("requests.get") as get:
            get.return_value = mock.Mock(status_code=200, raw=raw)
            sns.fetch_certificate(CERT_URL)
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

    def test_a_redirect_response_is_refused_rather_than_followed(self):
        cache.delete(f"sns:cert:{CERT_URL}")
        with mock.patch("requests.get") as get:
            get.return_value = mock.Mock(status_code=302, raw=mock.Mock())
            with self.assertRaises(sns.SNSVerificationError):
                sns.fetch_certificate(CERT_URL)

    def test_a_rejected_certificate_is_never_cached(self):
        """Otherwise one bad fetch poisons every later verification."""
        cache.delete(f"sns:cert:{CERT_URL}")
        pem = build_certificate(self.key, issuer_cn="Totally Legit CA")
        raw = mock.Mock()
        raw.read.return_value = pem
        with mock.patch("requests.get") as get:
            get.return_value = mock.Mock(status_code=200, raw=raw)
            with self.assertRaises(sns.SNSVerificationError):
                sns.fetch_certificate(CERT_URL)
        self.assertIsNone(cache.get(f"sns:cert:{CERT_URL}"))


class SuppressionSurvivesReplayTests(TestCase):
    """The event row and the suppression row used to be written separately.

    A failure between them left the event stored and the address still mailable,
    and every later redelivery hit the "already seen" branch and skipped the
    suppression — forever. The bug needed a partial failure to appear, which is
    why it survived the first review.
    """

    def test_a_replay_still_applies_missing_suppression(self):
        body = bounce_payload("lost@example.com", "Permanent")

        # Simulate the old broken outcome: the event exists, the suppression
        # does not.
        EmailEvent.objects.create(
            provider_message_id="replay-1",
            message_id="m-1",
            event_type=EmailEvent.Type.BOUNCE,
            recipient="lost@example.com",
            bounce_type=EmailEvent.BounceType.PERMANENT,
            payload={},
        )
        self.assertFalse(email_events.is_suppressed("lost@example.com"))

        # SNS redelivers. The insert collides, and suppression must still apply.
        email_events.record_ses_notification("replay-1", body)
        self.assertTrue(email_events.is_suppressed("lost@example.com"))

    def test_a_replay_of_a_transient_bounce_still_suppresses_nothing(self):
        body = bounce_payload("holiday@example.com", "Transient")
        email_events.record_ses_notification("replay-2", body)
        email_events.record_ses_notification("replay-2", body)
        self.assertFalse(email_events.is_suppressed("holiday@example.com"))
        self.assertEqual(
            EmailEvent.objects.filter(recipient="holiday@example.com").count(), 1
        )


class AmplificationLimitTests(TestCase):
    """One valid message must not become thousands of writes.

    SES allows at most 50 destinations per message, so anything larger is either
    a forged inner payload or an SES change we want to hear about.
    """

    def _many_recipient_complaint(self, count):
        addresses = [f"user{i}@example.com" for i in range(count)]
        return {
            "notificationType": "Complaint",
            "mail": {"messageId": "big-1", "destination": addresses},
            "complaint": {
                "complainedRecipients": [{"emailAddress": a} for a in addresses]
            },
        }

    def test_recipients_are_capped(self):
        created = email_events.record_ses_notification(
            "big-1", self._many_recipient_complaint(500)
        )
        self.assertEqual(len(created), 50)
        self.assertEqual(EmailEvent.objects.count(), 50)

    def test_the_payload_is_stored_once_not_per_recipient(self):
        """Storing a quarter-megabyte payload on every recipient row is how one
        request writes hundreds of megabytes."""
        email_events.record_ses_notification("big-2", self._many_recipient_complaint(10))
        # The primary key is a UUID, so select by the deterministic id rather
        # than by insertion order.
        first = EmailEvent.objects.get(provider_message_id="big-2")
        self.assertIn("complaint", first.payload)
        rest = EmailEvent.objects.exclude(provider_message_id="big-2")
        self.assertEqual(rest.count(), 9)
        for row in rest:
            self.assertEqual(row.payload, {"see": "big-2"})

    def test_non_string_recipients_are_ignored(self):
        body = {
            "notificationType": "Bounce",
            "mail": {"messageId": "odd-1", "destination": []},
            "bounce": {
                "bounceType": "Permanent",
                "bouncedRecipients": [
                    {"emailAddress": None},
                    {"emailAddress": {"nested": "object"}},
                    {"emailAddress": "real@example.com"},
                ],
            },
        }
        created = email_events.record_ses_notification("odd-1", body)
        self.assertEqual([e.recipient for e in created], ["real@example.com"])


def _resolver_returning_none(recipient):
    return None


def _resolver_that_explodes(recipient):
    raise RuntimeError("resolver is broken")


class TeamResolverTests(TestCase):
    """Attribution is delegated to the project, and must never cost the event.

    Losing the event would lose the suppression, which is the part that protects
    the sending reputation. So a resolver that is missing, unimportable or
    broken degrades to "no attribution" rather than failing the webhook.
    """

    def test_no_resolver_configured_means_no_attribution(self):
        created = email_events.record_ses_notification(
            "no-resolver", bounce_payload("x@example.com")
        )
        self.assertIsNone(created[0].team_id)

    @override_settings(
        SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER="speedpycom.tests.test_email_events._resolver_returning_none"
    )
    def test_a_resolver_returning_none_is_fine(self):
        created = email_events.record_ses_notification(
            "resolver-none", bounce_payload("y@example.com")
        )
        self.assertIsNone(created[0].team_id)

    @override_settings(
        SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER="speedpycom.tests.test_email_events._resolver_that_explodes"
    )
    def test_a_broken_resolver_does_not_lose_the_event_or_the_suppression(self):
        created = email_events.record_ses_notification(
            "resolver-boom", bounce_payload("z@example.com")
        )
        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0].team_id)
        self.assertTrue(email_events.is_suppressed("z@example.com"))

    @override_settings(SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER="nope.does.not.exist")
    def test_an_unimportable_resolver_does_not_lose_the_event(self):
        created = email_events.record_ses_notification(
            "resolver-missing", bounce_payload("w@example.com")
        )
        self.assertEqual(len(created), 1)
        self.assertTrue(email_events.is_suppressed("w@example.com"))


class NonObjectInnerMessageTests(TestCase):
    """json.loads returns whatever the JSON says, including a list.

    A signed message whose Message is `["not","an","object"]` used to reach
    .get(), raise, and be answered with 500 — so SNS retried a message that can
    never succeed, forever, until it disabled the endpoint.
    """

    def setUp(self):
        self.key, self.pem = make_keypair()

    def post(self, envelope):
        from cryptography.x509 import load_pem_x509_certificate

        with mock.patch.object(
            sns, "fetch_certificate",
            return_value=load_pem_x509_certificate(self.pem),
        ):
            return self.client.post(
                reverse("ses_events"),
                data=json.dumps(envelope),
                content_type="application/json",
            )

    @override_settings(SES_EVENT_TOPIC_ARN=TOPIC, CACHES=LOCMEM_CACHE)
    def test_a_json_list_is_accepted_not_retried(self):
        for message in ('["not", "an", "object"]', '"a string"', "42", "null"):
            with self.subTest(message=message):
                envelope = {
                    "Type": "Notification",
                    "MessageId": f"non-object-{message}",
                    "TopicArn": TOPIC,
                    "Message": message,
                    "Timestamp": "2026-08-21T10:00:00.000Z",
                }
                response = self.post(sign_envelope(envelope, self.key))
                self.assertEqual(response.status_code, 200)
        self.assertEqual(EmailEvent.objects.count(), 0)


class SendCountHonestyTests(TestCase):
    """A fully suppressed batch reports 0 sent, because 0 were sent.

    The first version returned the message count, on the belief that a lower
    count would make post_office retry. It does not: `Email.dispatch` calls
    `email_message().send()` and ignores the returned count, marking the row
    sent unless an exception is raised. So the inflated count bought nothing and
    misreported delivery to any direct caller of send_mail().
    """

    def setUp(self):
        email_events.suppress("blocked@example.com", SuppressedEmail.Reason.HARD_BOUNCE)

    def _backend(self):
        from speedpycom.email_backends import SuppressionAwareEmailBackend

        return SuppressionAwareEmailBackend()

    def test_a_fully_suppressed_batch_reports_zero_sent(self):
        from django.core.mail import EmailMessage

        message = EmailMessage(
            subject="hi", body="b", to=["blocked@example.com"]
        )
        self.assertEqual(self._backend().send_messages([message]), 0)

    def test_a_partly_suppressed_message_still_goes_to_the_rest(self):
        from django.core.mail import EmailMessage

        message = EmailMessage(
            subject="hi", body="b", to=["blocked@example.com", "ok@example.com"]
        )
        sent = self._backend().send_messages([message])
        self.assertEqual(sent, 1)
        self.assertEqual(message.to, ["ok@example.com"])
