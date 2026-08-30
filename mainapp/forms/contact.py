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
    class Meta:
        model = ContactSubmission
        fields = (
            "name",
            "company",
            "email",
            "phone",
            "company_size",
            "team",
            "project_budget",
            "message",
        )
        widgets = {
            "message": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project_budget"].required = True
        self.fields["company_size"].required = False
        self.fields["team"].required = False

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
            Div(
                Div(Field("name", placeholder="Jane Doe"), css_class="sm:col-span-1"),
                Div(Field("company", placeholder="Acme Inc."), css_class="sm:col-span-1"),
                Div(Field("email", placeholder="jane@acme.com"), css_class="sm:col-span-1"),
                Div(Field("phone", placeholder="+1 555 0100"), css_class="sm:col-span-1"),
                Div(Field("company_size"), css_class="sm:col-span-1"),
                Div(Field("team"), css_class="sm:col-span-1"),
                Div(Field("project_budget"), css_class="sm:col-span-2"),
                Div(Field("message", placeholder="Tell us about your project…"), css_class="sm:col-span-2"),
                css_class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2",
            ),
            Div(Field(HONEYPOT_FIELD), css_class="hidden"),
            *captcha,
            Submit(
                "submit",
                _("Let's Talk"),
                css_class="mt-6 w-full btn btn-contained btn-primary btn-lg",
            ),
        )
