"""Recording SES delivery events and enforcing suppression.

The write path for ``EmailEvent`` and ``SuppressedEmail``, plus the read used by
the pre-send guard. Nothing here trusts the transport: by the time a payload
reaches ``record_ses_notification`` its SNS signature has been verified, but the
*contents* are still just JSON from a third party, so every field is read
defensively and an unrecognised event type is stored rather than dropped.
"""

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.module_loading import import_string
from django.utils.dateparse import parse_datetime

from speedpycom.models import EmailEvent, SuppressedEmail

logger = structlog.get_logger(__name__)

#: SES notificationType / eventType -> our event type. SES uses different
#: casings depending on whether the event came from a configuration set event
#: destination or the legacy identity notifications, so both are mapped.
SES_EVENT_TYPES = {
    "send": EmailEvent.Type.SEND,
    "delivery": EmailEvent.Type.DELIVERY,
    "bounce": EmailEvent.Type.BOUNCE,
    "complaint": EmailEvent.Type.COMPLAINT,
    "reject": EmailEvent.Type.REJECT,
    "deliverydelay": EmailEvent.Type.DELIVERY_DELAY,
    "renderingfailure": EmailEvent.Type.RENDERING_FAILURE,
}

#: SES itself allows at most 50 destinations per message, so a genuine
#: notification never names more. Capping matters because each recipient costs
#: queries, an insert and a stored payload copy — one large notification would
#: otherwise amplify into thousands of writes.
MAX_RECIPIENTS = 50

SES_BOUNCE_TYPES = {
    "permanent": EmailEvent.BounceType.PERMANENT,
    "transient": EmailEvent.BounceType.TRANSIENT,
    "undetermined": EmailEvent.BounceType.UNDETERMINED,
}


def is_suppressed(email):
    """Whether we must not send to this address."""
    if not email:
        return False
    return SuppressedEmail.objects.filter(
        email=email.strip().lower(), released_at__isnull=True
    ).exists()


def suppressed_among(emails):
    """The suppressed subset of ``emails``, lowercased. One query, for the
    send-time guard where a message may have several recipients."""
    wanted = {e.strip().lower() for e in emails if e}
    if not wanted:
        return set()
    return set(
        SuppressedEmail.objects.filter(
            email__in=wanted, released_at__isnull=True
        ).values_list("email", flat=True)
    )


def suppress(email, reason, detail=""):
    """Add an address to the suppression list. Idempotent.

    Re-suppressing an address that was manually released is deliberate: a fresh
    hard bounce is new evidence, and it overrides the release.
    """
    email = (email or "").strip().lower()
    if not email:
        return None
    row, created = SuppressedEmail.objects.update_or_create(
        email=email,
        defaults={"reason": reason, "detail": detail[:2000], "released_at": None},
    )
    logger.warning(
        "email_suppressed", email=email, reason=reason, created=created
    )
    return row


def release(email):
    """Let an address be mailed again. Operator action, never automatic."""
    email = (email or "").strip().lower()
    from django.utils import timezone

    updated = SuppressedEmail.objects.filter(
        email=email, released_at__isnull=True
    ).update(released_at=timezone.now())
    if updated:
        logger.warning("email_suppression_released", email=email)
    return bool(updated)


def _recipients_for(event_type, body):
    """Pull the addresses an event concerns out of the SES payload shape."""
    if event_type == EmailEvent.Type.BOUNCE:
        return [
            r.get("emailAddress", "")
            for r in (body.get("bounce", {}).get("bouncedRecipients") or [])
        ]
    if event_type == EmailEvent.Type.COMPLAINT:
        return [
            r.get("emailAddress", "")
            for r in (body.get("complaint", {}).get("complainedRecipients") or [])
        ]
    if event_type == EmailEvent.Type.DELIVERY:
        return body.get("delivery", {}).get("recipients") or []
    if event_type == EmailEvent.Type.DELIVERY_DELAY:
        return [
            r.get("emailAddress", "")
            for r in (body.get("deliveryDelay", {}).get("delayedRecipients") or [])
        ]
    # send / reject / renderingFailure and anything unknown: fall back to the
    # message's own destination list.
    return (body.get("mail") or {}).get("destination") or []


def _resolve_team(recipient):
    """Best-effort tenant attribution, delegated to the project.

    ESP events carry no tenant, so only the project knows how to map a recipient
    address back to one — through its own contacts, memberships or whatever else
    it has. Point ``SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER`` at a dotted path taking
    the recipient address and returning a ``Team`` or ``None``.

    Unset by default, so a project with no tenants (or no interest in the
    attribution) pays nothing and stores null.

    **Whatever you write there must refuse to guess.** The obvious
    implementation — filter contacts by email, take the first team — silently
    misattributes an address that belongs to two customers. Return ``None`` when
    the answer is ambiguous; a null is honest, a wrong tenant is not.
    """
    path = getattr(settings, "SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER", "") or ""
    if not path:
        return None
    try:
        resolver = import_string(path)
    except ImportError:
        logger.exception("email_event_team_resolver_not_importable", path=path)
        return None
    try:
        return resolver(recipient)
    except Exception:
        # Attribution is a nice-to-have. It must never cost us the event, and
        # losing the event would cost us the suppression.
        logger.exception("email_event_team_resolver_failed", recipient=recipient)
        return None


def record_ses_notification(sns_message_id, body):
    """Record one SES event and apply suppression if it warrants it.

    ``body`` is the parsed SES notification (the ``Message`` of the SNS
    envelope). Returns the list of created events — one per recipient, because a
    single bounce notification can name several.

    Idempotent on ``sns_message_id``: SNS delivers at least once, so the same
    notification will arrive again.
    """
    raw_type = (body.get("eventType") or body.get("notificationType") or "").strip()
    event_type = SES_EVENT_TYPES.get(
        raw_type.lower().replace(" ", ""), EmailEvent.Type.OTHER
    )

    mail = body.get("mail") or {}
    message_id = mail.get("messageId", "") or ""
    occurred_at = parse_datetime(mail.get("timestamp") or "") or None

    bounce = body.get("bounce") or {}
    complaint = body.get("complaint") or {}
    bounce_type = SES_BOUNCE_TYPES.get(
        (bounce.get("bounceType") or "").lower(), ""
    )
    bounce_subtype = bounce.get("bounceSubType") or ""
    diagnostic = ""
    if event_type == EmailEvent.Type.BOUNCE:
        recipients_detail = bounce.get("bouncedRecipients") or [{}]
        diagnostic = recipients_detail[0].get("diagnosticCode", "") or ""
    elif event_type == EmailEvent.Type.COMPLAINT:
        diagnostic = complaint.get("complaintFeedbackType", "") or ""
    elif event_type == EmailEvent.Type.DELIVERY_DELAY:
        diagnostic = (body.get("deliveryDelay") or {}).get("delayType", "") or ""

    recipients = [r for r in _recipients_for(event_type, body) if isinstance(r, str) and r]
    if not recipients:
        logger.warning(
            "ses_event_without_recipient",
            sns_message_id=sns_message_id,
            event_type=event_type,
        )
        return []

    if len(recipients) > MAX_RECIPIENTS:
        # Not silently truncated — say so. SES never sends this, so it means
        # either a forged inner payload or an SES change worth knowing about.
        logger.warning(
            "ses_event_recipients_capped",
            sns_message_id=sns_message_id,
            claimed=len(recipients),
            cap=MAX_RECIPIENTS,
        )
        recipients = recipients[:MAX_RECIPIENTS]

    created = []
    for index, recipient in enumerate(recipients):
        recipient = recipient.strip().lower()
        # One SNS message can name several recipients, and provider_message_id
        # is unique — so it is suffixed per recipient. Deterministic, so a
        # redelivery collides with the same rows rather than inserting new ones.
        unique_id = sns_message_id if index == 0 else f"{sns_message_id}#{index}"
        # Whether this event warrants suppression does not depend on the row
        # existing, so decide it from the payload. That lets a replay still
        # apply suppression — see the IntegrityError branch below.
        warrants_suppression = event_type == EmailEvent.Type.COMPLAINT or (
            event_type == EmailEvent.Type.BOUNCE
            and bounce_type == EmailEvent.BounceType.PERMANENT
        )
        reason = (
            SuppressedEmail.Reason.COMPLAINT
            if event_type == EmailEvent.Type.COMPLAINT
            else SuppressedEmail.Reason.HARD_BOUNCE
        )
        detail = f"{raw_type} {bounce_subtype} {diagnostic}".strip()

        try:
            with transaction.atomic():
                event = EmailEvent.objects.create(
                    provider_message_id=unique_id,
                    message_id=message_id,
                    event_type=event_type,
                    recipient=recipient,
                    bounce_type=bounce_type,
                    bounce_subtype=bounce_subtype,
                    diagnostic=diagnostic[:2000],
                    occurred_at=occurred_at,
                    team=_resolve_team(recipient),
                    # The payload is stored once per notification, on the first
                    # recipient's row. Storing it on every row duplicated a
                    # blob that can be a quarter of a megabyte, so a single
                    # notification could write hundreds of megabytes.
                    payload=body if index == 0 else {"see": sns_message_id},
                )
                if warrants_suppression:
                    suppress(recipient, reason, detail=detail)
        except IntegrityError:
            logger.info(
                "ses_event_replayed",
                sns_message_id=unique_id,
                recipient=recipient,
            )
            # Do NOT skip suppression on a replay. The event row and the
            # suppression row used to be written in separate transactions, so a
            # failure between them left the event stored and the address still
            # mailable — and every later redelivery took this branch and skipped
            # the suppression forever. suppress() is idempotent, so re-asserting
            # it costs nothing and closes that hole.
            if warrants_suppression:
                suppress(recipient, reason, detail=detail)
            continue

        created.append(event)

    logger.info(
        "ses_event_recorded",
        event_type=event_type,
        recipients=len(created),
        message_id=message_id,
    )
    return created
