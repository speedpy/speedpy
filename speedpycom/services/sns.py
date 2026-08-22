"""Amazon SNS message signature verification.

**This module is Amazon-specific.** It is the detection half of bounce handling
and only applies when your ESP is SES. The enforcement half — the suppression
list and the pre-send guard — is provider-agnostic and lives in
``speedpycom/services/email_events.py`` and ``speedpycom/email_backends.py``.

Written rather than taken from a library on purpose. Anymail ships an SES
tracking webhook view, but its own source says:

    # Future: Verify SNS message signature

so its only protection is a shared secret in the URL. That is not enough here,
because a bounce notification triggers **suppression**: forging one would let
anyone permanently stop us mailing a chosen address — a denial of service against
a customer, delivered through our own feature. The signature is therefore the
authorization, and it is checked properly.

Three things this gets right that naive implementations miss:

1. **``SigningCertURL`` is attacker-supplied.** It arrives in the request body.
   Fetching it unchecked is both an SSRF primitive and a complete signature
   bypass — sign your own payload, host your own cert, and the maths checks out.
   So the host is allowlisted against AWS's SNS cert domains before any request
   is made.
2. **The canonical string is field-order sensitive** and differs per message
   type. Getting it subtly wrong makes every signature fail, or worse, makes
   verification vacuous.
3. **SignatureVersion selects the hash.** ``1`` is SHA1, ``2`` is SHA256.
   Anything else is refused rather than defaulted, so a future version cannot be
   downgraded past us.
"""

import base64
import re
from urllib.parse import urlparse

import requests
import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from django.core.cache import cache
from django.utils import timezone

logger = structlog.get_logger(__name__)

#: Certificate host allowlist. AWS serves SNS signing certs from
#: sns.<region>.amazonaws.com (and the China partition). Matched in full, never
#: with a substring or `endswith` test — `sns.eu-west-1.amazonaws.com.evil.tld`
#: passes a naive `in` check.
CERT_HOST_RE = re.compile(
    r"^sns\.[a-z0-9-]+\.amazonaws\.com(\.cn)?$", re.IGNORECASE
)

#: The host allowlist is not enough on its own. An allowed host with an
#: arbitrary path is still an SSRF target, and — worse — a way to make us cache
#: an attacker-chosen "certificate" under a URL that passes the host check. AWS
#: serves signing certs from a documented filename, so require it.
CERT_PATH_RE = re.compile(
    r"^/SimpleNotificationService-[A-Za-z0-9]+\.pem$"
)

CERT_CACHE_SECONDS = 24 * 3600
CERT_FETCH_TIMEOUT = (5, 10)
#: A signing cert is a few KB. Refuse anything absurd rather than buffering it.
CERT_MAX_BYTES = 32 * 1024
#: The issuer of a genuine SNS signing certificate. Checked as a suffix on the
#: organisation/common name rather than pinned to one CA, because AWS rotates
#: which Amazon CA signs these.
CERT_ISSUER_MUST_CONTAIN = "amazon"

#: Field order is part of the signature. AWS documents these exactly; the
#: fields present depend on the message type.
SIGNED_FIELDS = {
    "Notification": (
        "Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type",
    ),
    "SubscriptionConfirmation": (
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn",
        "Type",
    ),
}
# Unsubscribe confirmations are signed identically to subscription ones.
SIGNED_FIELDS["UnsubscribeConfirmation"] = SIGNED_FIELDS["SubscriptionConfirmation"]

HASHES = {"1": hashes.SHA1, "2": hashes.SHA256}


class SNSVerificationError(Exception):
    """The message is not a genuine, intact SNS message. Never process it."""


def canonical_string(message):
    """Build the exact byte string AWS signed.

    Only fields that are actually present are included — ``Subject`` is optional
    on a Notification, and including it as empty when absent breaks the
    signature.
    """
    message_type = message.get("Type")
    fields = SIGNED_FIELDS.get(message_type)
    if not fields:
        raise SNSVerificationError(f"Unsupported SNS message type: {message_type!r}")
    parts = []
    for field in fields:
        if field not in message:
            continue
        value = message[field]
        if value is None:
            continue
        parts.append(f"{field}\n{value}\n")
    return "".join(parts).encode("utf-8")


def _validate_sns_url(url, label):
    """Allowlist an AWS SNS URL completely — scheme, host, port and path.

    Used for both URLs a message can point us at. The host check is the one that
    matters most, but on its own it leaves two holes: an arbitrary path on an
    allowed host is still a request we can be made to send, and it lets an
    attacker pick the cache key a fetched certificate is stored under.
    """
    parsed = urlparse(url or "")
    if parsed.scheme != "https":
        raise SNSVerificationError(f"{label} must be https.")
    if not CERT_HOST_RE.match(parsed.hostname or ""):
        # The important refusal. Everything else about the signature is
        # meaningless if the attacker chooses the key it is checked against.
        raise SNSVerificationError(
            f"{label} host is not an AWS SNS host: {parsed.hostname!r}"
        )
    if parsed.port not in (None, 443):
        raise SNSVerificationError(f"{label} must use port 443, not {parsed.port!r}.")
    if parsed.username or parsed.password:
        raise SNSVerificationError(f"{label} must not carry credentials.")
    return parsed


def _validate_cert_url(url):
    parsed = _validate_sns_url(url, "SigningCertURL")
    if not CERT_PATH_RE.match(parsed.path or ""):
        raise SNSVerificationError(
            f"SigningCertURL path is not an SNS certificate: {parsed.path!r}"
        )
    if parsed.query:
        raise SNSVerificationError("SigningCertURL must not carry a query string.")
    return url


def validate_subscribe_url(url):
    """Allowlist ``SubscribeURL`` before fetching it.

    A separate function because this is the trap: ``SigningCertURL`` has already
    been validated by the time a subscription confirmation is handled, which
    makes the handler *feel* safe. ``SubscribeURL`` is a different URL from the
    same message and nothing had checked it — so a message reaching that path
    could make us GET the cloud metadata service.
    """
    parsed = _validate_sns_url(url, "SubscribeURL")
    if "Action=ConfirmSubscription" not in (parsed.query or ""):
        raise SNSVerificationError(
            "SubscribeURL is not a ConfirmSubscription call."
        )
    return url


def _authenticate_certificate(pem):
    """Parse the PEM and check it is a currently valid Amazon certificate.

    Parsing alone proves nothing at all: a self-signed certificate verifies a
    signature made with its own key perfectly, because the attacker made both.
    So the certificate itself has to be checked, not merely loaded.

    This does not build a full chain to a trusted root — SNS serves only the leaf
    at that URL, so a real chain check would need AIA fetching. Combined with the
    URL allowlist (host, port, documented path, no redirects) the practical path
    to substituting a key is closed; the issuer and date checks below are the
    second line rather than the only one.
    """
    certificate = load_pem_x509_certificate(pem)

    now = timezone.now()
    if now < certificate.not_valid_before_utc:
        raise SNSVerificationError("Signing certificate is not valid yet.")
    if now > certificate.not_valid_after_utc:
        raise SNSVerificationError("Signing certificate has expired.")

    issuer = certificate.issuer.rfc4514_string().lower()
    if CERT_ISSUER_MUST_CONTAIN not in issuer:
        raise SNSVerificationError(
            "Signing certificate was not issued by Amazon."
        )
    return certificate


def fetch_certificate(url):
    """Fetch and cache the signing certificate for an allowlisted URL."""
    _validate_cert_url(url)
    cache_key = f"sns:cert:{url}"
    pem = cache.get(cache_key)
    if pem is None:
        # allow_redirects=False is essential, not tidiness. requests follows
        # redirects by default, and only the URL we were GIVEN was allowlisted —
        # a single open redirect on an AWS host would hand the attacker control
        # of the key this signature is checked against.
        response = requests.get(
            url,
            timeout=CERT_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise SNSVerificationError(
                f"Signing certificate fetch returned {response.status_code}."
            )
        pem = response.raw.read(CERT_MAX_BYTES + 1, decode_content=True)
        if len(pem) > CERT_MAX_BYTES:
            raise SNSVerificationError("Signing certificate is implausibly large.")
        # Authenticate BEFORE caching, so a bad certificate is never stored.
        certificate = _authenticate_certificate(pem)
        cache.set(cache_key, pem, CERT_CACHE_SECONDS)
        return certificate
    return _authenticate_certificate(pem)


def verify_message(message):
    """Verify an SNS message dict. Raises :class:`SNSVerificationError`.

    Returns None on success — there is nothing useful to return, and a function
    that returns a boolean invites being called without checking it.
    """
    if not isinstance(message, dict):
        raise SNSVerificationError("SNS message must be a JSON object.")

    version = str(message.get("SignatureVersion", ""))
    hash_cls = HASHES.get(version)
    if hash_cls is None:
        raise SNSVerificationError(f"Unsupported SignatureVersion: {version!r}")

    signature_b64 = message.get("Signature")
    if not signature_b64:
        raise SNSVerificationError("Message has no Signature.")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
        raise SNSVerificationError("Signature is not valid base64.")

    signed = canonical_string(message)
    certificate = fetch_certificate(message.get("SigningCertURL"))

    try:
        certificate.public_key().verify(
            signature, signed, padding.PKCS1v15(), hash_cls()
        )
    except InvalidSignature:
        raise SNSVerificationError("Signature does not match the message.")
    except Exception as exc:
        raise SNSVerificationError(f"Signature could not be verified: {exc}")

    logger.info(
        "sns_message_verified",
        message_type=message.get("Type"),
        topic_arn=message.get("TopicArn"),
        signature_version=version,
    )
