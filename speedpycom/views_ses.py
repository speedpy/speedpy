"""SNS endpoint for SES delivery events.

A module rather than a package member: ``speedpycom/views.py`` already
exists, and adding a ``views/`` package alongside it shadows the module.

**Not routed by default.** Include ``speedpycom.urls_email_events`` from your
project urls when you actually use SES, so a project on another ESP does not
expose an endpoint it never needs.

CSRF-exempt because SNS is not a browser, and unauthenticated because the
**signature is the authorization** — see ``services/sns.py`` for why that is
verified here rather than delegated to Anymail.

Response discipline, which matters more than it looks: SNS retries on any
non-2xx and eventually disables an endpoint that keeps failing. So this returns
200 for anything it has genuinely dealt with — including a replayed event — and
non-2xx only for a message it refuses (403) or could not process for a reason a
retry might fix (500). A verification failure must NOT be a 500: retrying a
forged message forever is pointless.
"""

import json

import structlog
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from speedpycom.services import sns
from speedpycom.services.email_events import record_ses_notification

logger = structlog.get_logger(__name__)

#: SNS posts this content type; some tools post application/json.
MAX_BODY_BYTES = 256 * 1024


@method_decorator(csrf_exempt, name="dispatch")
class SESEventWebhookView(View):
    """Receive SES event notifications delivered through SNS."""

    def post(self, request, *args, **kwargs):
        if len(request.body or b"") > MAX_BODY_BYTES:
            logger.warning("sns_body_too_large", size=len(request.body or b""))
            return HttpResponse(status=413)

        try:
            envelope = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("sns_body_not_json")
            return HttpResponse(status=400)

        # Cheap claimed-topic check FIRST, before verification, because
        # verification fetches a certificate over the network. Without this, a
        # flood of foreign-topic messages makes us issue an outbound request per
        # message. The authoritative check is repeated after verification below —
        # this one is only an unauthenticated claim.
        if not self._topic_is_expected(envelope.get("TopicArn", "")):
            logger.warning(
                "sns_unexpected_topic_claimed",
                topic_arn=envelope.get("TopicArn", ""),
            )
            return HttpResponse(status=403)

        try:
            sns.verify_message(envelope)
        except sns.SNSVerificationError as exc:
            # 403, not 500: a forged or malformed message will never verify, so
            # asking SNS to retry it forever achieves nothing.
            logger.warning("sns_verification_failed", error=str(exc))
            return HttpResponse(status=403)
        except Exception as exc:
            # Fetching the certificate failed — that IS worth a retry.
            logger.exception("sns_verification_error", error=str(exc))
            return HttpResponse(status=500)

        if not self._topic_is_expected(envelope.get("TopicArn", "")):
            logger.warning(
                "sns_unexpected_topic", topic_arn=envelope.get("TopicArn", "")
            )
            return HttpResponse(status=403)

        message_type = envelope.get("Type")
        if message_type == "SubscriptionConfirmation":
            return self._confirm_subscription(envelope)
        if message_type == "UnsubscribeConfirmation":
            logger.warning(
                "sns_unsubscribe_confirmation",
                topic_arn=envelope.get("TopicArn", ""),
            )
            return HttpResponse(status=200)
        if message_type != "Notification":
            return HttpResponse(status=400)

        try:
            body = json.loads(envelope.get("Message") or "{}")
        except ValueError:
            logger.warning("sns_inner_message_not_json")
            # Verified as genuinely from AWS but unparseable — a retry will not
            # help, so accept it rather than have SNS hammer us.
            return HttpResponse(status=200)

        if not isinstance(body, dict):
            # json.loads happily returns a list, a string or None. Letting one
            # through means .get() raises, we answer 500, and SNS retries a
            # message that can never succeed — forever.
            logger.warning("sns_inner_message_not_object", kind=type(body).__name__)
            return HttpResponse(status=200)

        try:
            record_ses_notification(envelope.get("MessageId", ""), body)
        except Exception:
            logger.exception("ses_event_processing_failed")
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    def _topic_is_expected(self, topic_arn):
        """Only accept the topic we were configured for.

        Without this, anyone could point their own SNS topic at this endpoint
        and — since their messages carry a valid AWS signature — have us confirm
        the subscription and ingest their events. An unset setting accepts any
        topic, so that the subscription can be established before the ARN is
        known; set it as soon as the topic exists.
        """
        expected = getattr(settings, "SES_EVENT_TOPIC_ARN", "") or ""
        if not expected:
            logger.warning("sns_topic_arn_not_configured", topic_arn=topic_arn)
            return True
        return topic_arn == expected

    def _confirm_subscription(self, envelope):
        """Complete the SNS handshake by fetching SubscribeURL.

        Only reached after the signature verified AND the topic matched, so we
        are not confirming a subscription somebody else created.
        """
        import requests

        subscribe_url = envelope.get("SubscribeURL") or ""
        try:
            # Validate THIS url, not SigningCertURL. They are different URLs from
            # the same message, and an earlier version of this code checked the
            # certificate URL here — which feels safe and protects nothing,
            # because SubscribeURL is what we then fetch. Unchecked, a message
            # reaching this path can make us GET the cloud metadata service.
            sns.validate_subscribe_url(subscribe_url)
        except sns.SNSVerificationError as exc:
            # Refused, not retried: a bad SubscribeURL will never become good.
            logger.warning("sns_subscribe_url_refused", error=str(exc))
            return HttpResponse(status=403)

        try:
            response = requests.get(
                subscribe_url,
                timeout=(5, 10),
                allow_redirects=False,
                stream=True,
            )
            if response.status_code != 200:
                raise ValueError(f"confirmation returned {response.status_code}")
            # Bound the read. We do not use the body; SNS returns a small XML
            # document and we only care that the call succeeded.
            response.raw.read(64 * 1024, decode_content=True)
        except Exception as exc:
            logger.exception("sns_subscription_confirm_failed", error=str(exc))
            return HttpResponse(status=500)
        logger.warning(
            "sns_subscription_confirmed", topic_arn=envelope.get("TopicArn", "")
        )
        return HttpResponse(status=200)
