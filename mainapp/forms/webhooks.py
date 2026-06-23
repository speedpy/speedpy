from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Div
from crispy_tailwind.layout import Submit
from django.utils.translation import gettext_lazy as _

from mainapp.webhooks.events import WebhookEvent


class WebhookEndpointForm(forms.Form):
    """Form for creating or editing a webhook endpoint."""

    name = forms.CharField(
        max_length=255,
        required=False,
        help_text=_("Optional human-readable label for this endpoint."),
    )
    url = forms.URLField(
        max_length=2048,
        help_text=_("HTTPS URL that receives webhook payloads."),
    )
    events = forms.MultipleChoiceField(
        choices=[("*", "All events")] + list(WebhookEvent.CHOICES),
        widget=forms.CheckboxSelectMultiple(attrs={"class": "checkbox"}),
        help_text=_("Select which events this endpoint receives."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("name", placeholder="My webhook"),
            Field("url", placeholder="https://example.com/webhook"),
            Div(
                Field("events"),
                css_class="text-fg [&_label]:text-fg [&_label]:font-normal [&_label]:cursor-pointer",
            ),
            Submit(
                "submit",
                _("Create webhook"),
                css_class="btn btn-contained btn-primary",
            ),
        )

    def clean_url(self, ):
        url = self.cleaned_data["url"]
        if not url.startswith("https://"):
            raise forms.ValidationError(_("Only HTTPS URLs are allowed."))
        return url

    def clean_events(self):
        events = self.cleaned_data["events"]
        if "*" in events:
            return ["*"]
        return events
