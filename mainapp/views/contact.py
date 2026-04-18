from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView

from mainapp.forms import ContactForm
from mainapp.models import ContactSubmission


class ContactView(CreateView):
    model = ContactSubmission
    form_class = ContactForm
    template_name = "mainapp/contact.html"
    success_url = reverse_lazy("contact")

    def form_valid(self, form):
        messages.success(
            self.request,
            "Thanks for reaching out — we'll be in touch shortly.",
        )
        return super().form_valid(form)
