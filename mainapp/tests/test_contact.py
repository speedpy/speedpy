"""Contact form: it saves, notifies, honeypots bots, and gates reCAPTCHA."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from mainapp.forms import ContactForm
from mainapp.forms.contact import HONEYPOT_FIELD
from mainapp.models import ContactSubmission

VALID = {
    "name": "Jane Doe",
    "email": "jane@acme.com",
    "message": "Please get in touch about a refund.",
}


class ContactViewTests(TestCase):
    def test_valid_submission_saves_and_queues_notification(self):
        with patch("mainapp.views.contact.current_app") as current_app:
            send_task = current_app.send_task
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(reverse("contact"), VALID)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactSubmission.objects.count(), 1)
        sub = ContactSubmission.objects.get()
        send_task.assert_called_once_with(
            "send_contact_notification_email", kwargs={"submission_id": sub.pk}
        )

    def test_honeypot_submission_is_dropped(self):
        payload = {**VALID, HONEYPOT_FIELD: "http://spam.example"}
        with patch("mainapp.views.contact.current_app") as current_app:
            send_task = current_app.send_task
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(reverse("contact"), payload)
        self.assertEqual(resp.status_code, 302)  # looks like success to the bot
        self.assertEqual(ContactSubmission.objects.count(), 0)  # but nothing saved
        send_task.assert_not_called()


class ContactFormRecaptchaTests(TestCase):
    @override_settings(RECAPTCHA_PUBLIC_KEY="", RECAPTCHA_PRIVATE_KEY="")
    def test_no_captcha_field_when_unconfigured(self):
        self.assertNotIn("captcha", ContactForm().fields)

    @override_settings(RECAPTCHA_PUBLIC_KEY="pub", RECAPTCHA_PRIVATE_KEY="priv")
    def test_captcha_field_added_when_configured(self):
        self.assertIn("captcha", ContactForm().fields)


class OpsNotifyTests(TestCase):
    @override_settings(TELEGRAM_OPS_BOT_TOKEN="", TELEGRAM_OPS_CHAT_ID="")
    def test_noop_when_unconfigured(self):
        from mainapp.ops_notify import notify_ops

        with patch("project.celeryapp.app.send_task") as send_task:
            with self.captureOnCommitCallbacks(execute=True):
                notify_ops("hi")
        send_task.assert_not_called()

    @override_settings(TELEGRAM_OPS_BOT_TOKEN="tok", TELEGRAM_OPS_CHAT_ID="123")
    def test_enqueues_when_configured(self):
        from mainapp.ops_notify import notify_ops

        with patch("project.celeryapp.app.send_task") as send_task:
            with self.captureOnCommitCallbacks(execute=True):
                notify_ops("hi")
        send_task.assert_called_once_with(
            "send_ops_telegram_notification", args=["hi"]
        )
