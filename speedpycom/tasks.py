"""Framework-level periodic tasks.

Discovered by ``app.autodiscover_tasks()`` like any other app's ``tasks.py``.
Kept thin on purpose: the logic lives in ``speedpycom/services/`` so it can be
subclassed and called from a management command too.
"""

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="purge_unconfirmed_accounts")
def purge_unconfirmed_accounts():
    """Delete signups that never confirmed an email address.

    A no-op unless ``SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS`` is set, so the
    beat entry can ship enabled without deleting anybody's users by surprise.
    """
    from speedpycom.services.account_purge import get_purge

    report = get_purge().run()
    return (
        "Purge disabled"
        if not report["enabled"]
        else f"Purged {report['purged']} account(s), {report['failed']} failed"
    )
