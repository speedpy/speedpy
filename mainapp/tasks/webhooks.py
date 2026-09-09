import json
import time
from datetime import timedelta

import httpx
import structlog
from celery import shared_task
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from mainapp.models.webhooks import WebhookDelivery, WebhookEndpoint
from mainapp.webhooks.lifecycle import deactivate_endpoint, endpoint_is_deliverable
from mainapp.webhooks.signing import sign

logger = structlog.get_logger(__name__)

# Retry schedule: 60s * 2^attempt, capped at 3600s (1 hour), max 8 retries.
MAX_RETRIES = 8
BACKOFF_BASE = 60
BACKOFF_CAP = 3600

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30

# Retention for delivery logs (payloads/response bodies can carry PII).
DEFAULT_DELIVERY_RETENTION_DAYS = 30
DEFAULT_DELIVERY_DELETE_DAYS = 90

# Terminal statuses — never mutate a delivery that already reached one of these.
_TERMINAL_STATUSES = frozenset({
    WebhookDelivery.Status.SUCCESS,
    WebhookDelivery.Status.FAILED,
    WebhookDelivery.Status.DISABLED,
    WebhookDelivery.Status.REDACTED,
})

# Status codes that should be retried.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@shared_task(bind=True, name="deliver_webhook", max_retries=MAX_RETRIES, acks_late=True)
def deliver_webhook(self, delivery_id: int):
    """Deliver a single webhook payload to the subscriber endpoint."""
    try:
        delivery = WebhookDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        logger.warning("webhook_delivery_not_found", delivery_id=delivery_id)
        return

    endpoint = delivery.endpoint

    # Skip deliveries that already reached a terminal status.
    if delivery.status in _TERMINAL_STATUSES:
        logger.info("webhook_delivery_skipped", delivery_id=delivery_id, status=delivery.status)
        return

    # Skip if endpoint was deactivated between enqueue and execution. These
    # early terminal writes are compare-and-set from PENDING: under acks_late two
    # workers can hold the same PENDING row, and the retention purge may have
    # since redacted it — a blind save() would resurrect a terminal row.
    if not endpoint.is_active:
        WebhookDelivery.objects.filter(
            pk=delivery_id, status=WebhookDelivery.Status.PENDING
        ).update(
            status=WebhookDelivery.Status.DISABLED,
            error_message="Endpoint was inactive at delivery time.",
            updated_at=timezone.now(),
        )
        logger.info("webhook_delivery_disabled", delivery_id=delivery_id, endpoint_url=endpoint.url)
        return

    # Re-check the connection lifecycle right before sending: the row was
    # enqueued on the caller's commit, so a revocation in that window would
    # otherwise still deliver. Fail closed.
    deliverable, reason = endpoint_is_deliverable(endpoint)
    if not deliverable:
        WebhookDelivery.objects.filter(
            pk=delivery_id, status=WebhookDelivery.Status.PENDING
        ).update(
            status=WebhookDelivery.Status.DISABLED,
            error_message=f"Endpoint connection no longer valid: {reason}.",
            updated_at=timezone.now(),
        )
        logger.info(
            "webhook_delivery_disabled",
            delivery_id=delivery_id,
            endpoint_url=endpoint.url,
            reason=reason,
        )
        return

    # Atomically claim the delivery: only transition PENDING → IN_FLIGHT.
    # This prevents duplicate POSTs when acks_late causes task redelivery.
    updated = WebhookDelivery.objects.filter(
        pk=delivery_id,
        status=WebhookDelivery.Status.PENDING,
    ).update(
        status=WebhookDelivery.Status.IN_FLIGHT,
        attempts=F("attempts") + 1,
        updated_at=timezone.now(),
    )
    if not updated:
        logger.info("webhook_delivery_skipped", delivery_id=delivery_id, status=delivery.status)
        return

    delivery.refresh_from_db()

    body = json.dumps(delivery.payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = sign(endpoint.secret, timestamp, body)

    headers = {
        "Content-Type": "application/json",
        "X-SpeedPy-Signature": signature,
        "X-SpeedPy-Timestamp": timestamp,
        "X-SpeedPy-Event": delivery.event_type,
        "X-SpeedPy-Delivery": delivery.event_id,
    }

    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT),
        ) as client:
            response = client.post(endpoint.url, content=body, headers=headers)
    except httpx.TimeoutException as exc:
        _handle_retryable_failure(self, delivery, error_message=f"Timeout: {exc}")
        return
    except httpx.HTTPError as exc:
        _handle_retryable_failure(self, delivery, error_message=f"Network error: {exc}")
        return

    delivery.http_status_code = response.status_code
    delivery.response_body = response.text[:WebhookDelivery.RESPONSE_BODY_MAX_LENGTH]

    if 200 <= response.status_code < 300:
        delivery.status = WebhookDelivery.Status.SUCCESS
        delivery.delivered_at = timezone.now()
        delivery.save(update_fields=[
            "status", "http_status_code", "response_body", "delivered_at", "updated_at",
        ])
        logger.info(
            "webhook_delivered",
            delivery_id=delivery_id,
            endpoint_url=endpoint.url,
            status_code=response.status_code,
        )
    elif response.status_code in RETRYABLE_STATUS_CODES:
        _handle_retryable_failure(
            self,
            delivery,
            error_message=f"HTTP {response.status_code}",
        )
    elif response.status_code == 410:
        # 410 Gone means the subscriber (e.g. a deleted/paused Zapier hook) is
        # gone for good. Deactivate the endpoint so it stops generating one
        # failed delivery per event forever — but with a compare-and-set on the
        # URL, so a concurrent re-point (PATCH that changed the URL) is not
        # turned off by a stale 410 from the old target.
        deactivate_endpoint(
            endpoint,
            reason="subscriber_gone_410",
            expected_url=endpoint.url,
        )
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.error_message = "HTTP 410 — endpoint deactivated (subscriber gone)"
        delivery.save(update_fields=[
            "status", "http_status_code", "response_body", "error_message", "updated_at",
        ])
        logger.warning(
            "webhook_delivery_gone",
            delivery_id=delivery_id,
            endpoint_url=endpoint.url,
            status_code=response.status_code,
        )
    else:
        # Permanent failure (other 4xx, 501, or other non-retryable).
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.error_message = f"HTTP {response.status_code}"
        delivery.save(update_fields=[
            "status", "http_status_code", "response_body", "error_message", "updated_at",
        ])
        logger.warning(
            "webhook_delivery_failed_permanently",
            delivery_id=delivery_id,
            endpoint_url=endpoint.url,
            status_code=response.status_code,
        )


def _handle_retryable_failure(task, delivery, error_message: str):
    """Schedule a retry with exponential backoff, or mark as permanently failed."""
    attempt = delivery.attempts  # already incremented via atomic update
    countdown = min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP)

    if attempt > MAX_RETRIES:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.error_message = f"{error_message} (exhausted {MAX_RETRIES} retries)"
        delivery.save(update_fields=[
            "status", "http_status_code", "response_body", "error_message", "updated_at",
        ])
        logger.warning(
            "webhook_delivery_max_retries",
            delivery_id=delivery.pk,
            attempts=attempt,
            error=error_message,
        )
        return

    delivery.status = WebhookDelivery.Status.PENDING
    delivery.error_message = error_message
    delivery.save(update_fields=[
        "status", "http_status_code", "response_body", "error_message", "updated_at",
    ])

    logger.info(
        "webhook_delivery_retry_scheduled",
        delivery_id=delivery.pk,
        attempt=attempt,
        countdown=countdown,
        error=error_message,
    )
    task.retry(countdown=countdown, exc=None)


@shared_task(name="webhooks.reconcile_endpoints", acks_late=True)
def reconcile_endpoints():
    """Deactivate active endpoints whose connection is no longer valid.

    Runs the same rule as dispatch over active endpoints and deactivates the
    failures, so the dashboard shows the truth and the per-event skip log does
    not repeat forever. Idempotent: an endpoint that is already inactive is a
    no-op.
    """
    deactivated = 0
    checked = 0
    endpoints = WebhookEndpoint.objects.filter(is_active=True).select_related("team", "application")
    for endpoint in endpoints.iterator():
        checked += 1
        deliverable, reason = endpoint_is_deliverable(endpoint)
        if deliverable:
            continue
        if deactivate_endpoint(endpoint, reason=f"reconcile:{reason}"):
            deactivated += 1

    logger.info("webhook_endpoints_reconciled", checked=checked, deactivated=deactivated)
    return {"checked": checked, "deactivated": deactivated}


def _delivery_retention_days() -> int:
    return int(
        getattr(settings, "WEBHOOK_DELIVERY_RETENTION_DAYS", DEFAULT_DELIVERY_RETENTION_DAYS)
    )


def _delivery_delete_days() -> int:
    return int(
        getattr(settings, "WEBHOOK_DELIVERY_DELETE_DAYS", DEFAULT_DELIVERY_DELETE_DAYS)
    )


@shared_task(name="webhooks.purge_deliveries", acks_late=True)
def purge_deliveries(batch_size: int = 1000):
    """Redact old delivery payloads, then delete very old rows.

    Delivery rows keep the full ``payload`` envelope and ``response_body``,
    which can carry third-party PII (e.g. survey follow-up answers). After
    ``WEBHOOK_DELIVERY_RETENTION_DAYS`` the content is redacted in place and the
    row is marked ``REDACTED`` (a terminal status), so a later retry can never
    re-send a redacted payload. After ``WEBHOOK_DELIVERY_DELETE_DAYS`` the row
    is deleted outright. Batched and idempotent.
    """
    now = timezone.now()
    redact_before = now - timedelta(days=_delivery_retention_days())
    delete_before = now - timedelta(days=_delivery_delete_days())

    # Redact FIRST, then delete only what is redacted. Only terminal, settled
    # rows are ever touched — never PENDING/IN_FLIGHT — so a live retry or an
    # in-flight POST cannot be redacted or deleted out from under itself. Each
    # redaction is a compare-and-set on the exact status read, so a status
    # transition in between is left alone rather than clobbered.
    redactable = (
        WebhookDelivery.Status.SUCCESS,
        WebhookDelivery.Status.FAILED,
        WebhookDelivery.Status.DISABLED,
    )
    redacted = 0
    while True:
        batch = list(
            WebhookDelivery.objects.filter(
                created_at__lt=redact_before, status__in=redactable
            ).only("pk", "event_type", "error_message", "status")[:batch_size]
        )
        if not batch:
            break
        for delivery in batch:
            first_line = (delivery.error_message or "").splitlines()[0] if delivery.error_message else ""
            flipped = WebhookDelivery.objects.filter(
                pk=delivery.pk, status=delivery.status
            ).update(
                payload={"redacted": True, "event_type": delivery.event_type},
                response_body="",
                error_message=first_line,
                status=WebhookDelivery.Status.REDACTED,
                updated_at=timezone.now(),
            )
            redacted += flipped

    # Delete only redacted rows past the delete window: they are terminal and
    # already stripped of content, so deletion can never remove a live row or
    # race a retry (a retry can only touch a FAILED row, never a REDACTED one).
    deleted = 0
    while True:
        pks = list(
            WebhookDelivery.objects.filter(
                created_at__lt=delete_before, status=WebhookDelivery.Status.REDACTED
            ).values_list("pk", flat=True)[:batch_size]
        )
        if not pks:
            break
        deleted += WebhookDelivery.objects.filter(pk__in=pks).delete()[0]

    logger.info("webhook_deliveries_purged", redacted=redacted, deleted=deleted)
    return {"redacted": redacted, "deleted": deleted}
