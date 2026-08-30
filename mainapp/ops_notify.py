"""Dispatch ops notifications to the admin/site-owner Telegram chat.

Call :func:`notify_ops` from anywhere (views, signals, webhook handlers, tasks).
The actual HTTP request runs asynchronously in the ``send_ops_telegram_notification``
Celery task, and the enqueue is deferred to ``transaction.on_commit`` so we never
notify about a database change that ends up rolled back.

Ops notifications are **silently disabled** until both ``TELEGRAM_OPS_BOT_TOKEN``
and ``TELEGRAM_OPS_CHAT_ID`` are configured, so this is safe to call in every
environment (local, tests, CI) without any setup.
"""

from html import escape

import structlog
from django.conf import settings
from django.db import transaction

logger = structlog.get_logger(__name__)


def ops_notifications_enabled():
    """True only when both the bot token and the chat id are configured."""
    return bool(
        getattr(settings, "TELEGRAM_OPS_BOT_TOKEN", "")
        and getattr(settings, "TELEGRAM_OPS_CHAT_ID", "")
    )


def notify_ops(text):
    """Enqueue an ops notification, deferred until the current transaction commits.

    No-ops when Telegram ops notifications are not configured. Never raises: a
    notification must never break the request that triggered it.
    """
    if not ops_notifications_enabled():
        return

    from project import celery_app

    def _dispatch():
        try:
            celery_app.send_task("send_ops_telegram_notification", args=[text])
        except Exception as exc:  # never let a notification break the caller
            logger.warning("Failed to enqueue ops notification", error=str(exc))

    transaction.on_commit(_dispatch)


def esc(value):
    """HTML-escape a value for safe embedding in a Telegram HTML message."""
    return escape(str(value if value is not None else ""))
