"""Notify the team when a contact-form submission arrives.

Sends a single email to ``CONTACT_NOTIFICATION_EMAIL`` (which defaults to
``SUPPORT_EMAIL``) with the submitter's details and a ``Reply-To`` set to their
address, so a reply goes straight back to them. No-ops when no recipient is
configured. Dispatched from ``ContactView`` on ``transaction.on_commit`` so it
only fires once the submission row is committed.
"""

import structlog
from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string
from post_office import mail

from mainapp.models import ContactSubmission

logger = structlog.get_logger(__name__)


@shared_task(name="send_contact_notification_email")
def send_contact_notification_email(submission_id):
    recipient = getattr(settings, "CONTACT_NOTIFICATION_EMAIL", "") or getattr(
        settings, "SUPPORT_EMAIL", ""
    )
    if not recipient:
        logger.warning(
            "Contact notification skipped — no CONTACT_NOTIFICATION_EMAIL/SUPPORT_EMAIL set",
            submission_id=submission_id,
        )
        return

    submission = ContactSubmission.objects.get(pk=submission_id)
    context = {"submission": submission}
    subject = f"New contact submission from {submission.name}"

    try:
        html_message = render_to_string("emails/contact_notification.html", context)
    except Exception:
        # A fork may delete the template; fall back to a plain body rather than fail.
        html_message = (
            f"<p>New contact submission.</p>"
            f"<p>Name: {submission.name}<br>Email: {submission.email}</p>"
            f"<p>{submission.message}</p>"
        )

    mail.send(
        recipient,
        settings.DEFAULT_FROM_EMAIL,
        subject=subject,
        html_message=html_message,
        headers={"Reply-To": submission.email},
        priority="now",
    )
