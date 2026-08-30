from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Div
from crispy_tailwind.layout import Submit
from django import forms
from django.utils.translation import gettext_lazy as _

from mainapp.models import ContactSubmission
from usermodel.forms import attach_recaptcha

#: Name of the honeypot field. Must stay empty; a bot that fills it is dropped by
#: the view. Kept out of the visible layout via a display:none wrapper.
HONEYPOT_FIELD = "website"


class ContactForm(forms.ModelForm):
    """A general "get in touch" form: name, email, and a message.

    The ``ContactSubmission`` model still carries optional sales fields (company,
    budget, ...) for forks that want a lead-capture form; they are simply left off
    this form and saved empty.
    """

    class Meta:
        model = ContactSubmission
        fields = ("name", "email", "message")
        widgets = {
            "message": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = _("Name")
        self.fields["email"].label = _("Email")
        self.fields["message"].label = _("Message")

        # Honeypot: a plausible-looking field real users never see or fill.
        self.fields[HONEYPOT_FIELD] = forms.CharField(
            required=False,
            label="",
            widget=forms.TextInput(
                attrs={"autocomplete": "off", "tabindex": "-1", "aria-hidden": "true"}
            ),
        )

        # reCAPTCHA v3, only when keys are configured (returns [] otherwise).
        captcha = attach_recaptcha(self)

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("name", placeholder="Jane Doe"),
            Field("email", placeholder="jane@example.com"),
            Field("message", placeholder="How can we help?"),
            Div(Field(HONEYPOT_FIELD), css_class="hidden"),
            *captcha,
            # Name must NOT be "submit": a field named "submit" shadows the form's
            # native form.submit(), which reCAPTCHA v3 calls after validating.
            Submit(
                "action",
                _("Send message"),
                css_class="mt-6 w-full btn btn-contained btn-primary btn-lg",
            ),
        )
