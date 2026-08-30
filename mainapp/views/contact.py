from functools import partial

from celery import current_app
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from mainapp.forms import ContactForm
from mainapp.forms.contact import HONEYPOT_FIELD
from mainapp.models import ContactSubmission
from mainapp.ops_notify import esc, notify_ops

SUCCESS_MESSAGE = "Thanks for reaching out — we'll be in touch shortly."


class ContactView(CreateView):
    model = ContactSubmission
    form_class = ContactForm
    template_name = "mainapp/contact.html"
    success_url = reverse_lazy("contact")

    def form_valid(self, form):
        # Honeypot tripped: pretend success, but do not save or notify.
        # (Redirect straight to success_url — get_success_url() would deref the
        # unsaved self.object.)
        if form.cleaned_data.get(HONEYPOT_FIELD):
            messages.success(self.request, SUCCESS_MESSAGE)
            return HttpResponseRedirect(str(self.success_url))

        response = super().form_valid(form)  # saves the submission -> self.object
        submission = self.object

        # Email the team, and ping the ops Telegram chat, once the row commits.
        transaction.on_commit(
            partial(
                current_app.send_task,
                "send_contact_notification_email",
                kwargs={"submission_id": submission.pk},
            )
        )
        notify_ops(
            f"📨 <b>New contact submission</b>\n"
            f"Name: {esc(submission.name)}\n"
            f"Email: {esc(submission.email)}"
        )

        messages.success(self.request, SUCCESS_MESSAGE)
        return response
