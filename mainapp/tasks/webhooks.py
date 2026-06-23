import json
import time

import httpx
import structlog
from celery import shared_task
from django.db.models import F
from django.utils import timezone

from mainapp.models.webhooks import WebhookDelivery
from mainapp.webhooks.signing import sign

logger = structlog.get_logger(__name__)

# Retry schedule: 60s * 2^attempt, capped at 3600s (1 hour), max 8 retries.
MAX_RETRIES = 8
BACKOFF_BASE = 60
BACKOFF_CAP = 3600

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30

# Terminal statuses — never mutate a delivery that already reached one of these.
_TERMINAL_STATUSES = frozenset({
    WebhookDelivery.Status.SUCCESS,
    WebhookDelivery.Status.FAILED,
    WebhookDelivery.Status.DISABLED,
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

    # Skip if endpoint was deactivated between enqueue and execution.
    if not endpoint.is_active:
        delivery.status = WebhookDelivery.Status.DISABLED
        delivery.error_message = "Endpoint was inactive at delivery time."
        delivery.save(update_fields=["status", "error_message", "updated_at"])
        logger.info("webhook_delivery_disabled", delivery_id=delivery_id, endpoint_url=endpoint.url)
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
    else:
        # Permanent failure (4xx, 501, or other non-retryable).
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
