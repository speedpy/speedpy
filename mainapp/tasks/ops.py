"""Celery task that performs the actual Telegram ops-notification HTTP call.

Kept separate from the ``mainapp.ops_notify`` dispatcher so the blocking
``requests.post`` never runs in-request. Disabled silently when the bot token or
chat id are not configured; callers own HTML-escaping of any untrusted content
embedded in ``text`` (use ``mainapp.ops_notify.esc``).
"""

import requests
import structlog
from celery import shared_task
from django.conf import settings

logger = structlog.get_logger(__name__)

TELEGRAM_API_TIMEOUT = 10


@shared_task(name="send_ops_telegram_notification")
def send_ops_telegram_notification(text):
    """Send an ops notification message to the configured Telegram chat."""
    token = getattr(settings, "TELEGRAM_OPS_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_OPS_CHAT_ID", "")
    if not token or not chat_id:
        logger.debug("Telegram ops notifications disabled — skipping", configured=False)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TELEGRAM_API_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to send Telegram ops notification", error=str(exc))
