import time
import uuid

from django.db import transaction

from mainapp.models.webhooks import WebhookDelivery, WebhookEndpoint


def dispatch_event(team, event_type: str, data: dict) -> list[int]:
    """Create delivery rows for all matching endpoints and enqueue tasks.

    Tasks are enqueued via ``transaction.on_commit`` so that the delivery
    row is visible to the worker when it runs (important when
    ``ATOMIC_REQUESTS`` is enabled).

    Returns a list of created ``WebhookDelivery`` PKs.
    """
    from mainapp.tasks.webhooks import deliver_webhook

    endpoints = WebhookEndpoint.objects.filter(team=team, is_active=True)
    delivery_ids: list[int] = []

    for endpoint in endpoints:
        if not endpoint.subscribes_to(event_type):
            continue

        event_id = f"evt_{uuid.uuid4().hex}"
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": int(time.time()),
            "api_version": "2026-06-01",
            "data": data,
        }

        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        # Enqueue after commit so the row is visible to the worker.
        transaction.on_commit(lambda pk=delivery.pk: deliver_webhook.delay(pk))
        delivery_ids.append(delivery.pk)

    return delivery_ids
