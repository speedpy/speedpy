from allauth.account.forms import (
    SignupForm,
    PasswordField,
    LoginForm,
    ResetPasswordForm,
    ResetPasswordKeyForm,
    ChangePasswordForm,
    AddEmailForm,
)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout, Field
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV3

from crispy_tailwind.layout import Submit
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from speedpycom.widgets import ImageUploadInput
from usermodel.models import User
from speedpycom.services import email_deliverability


def recaptcha_enabled():
    """reCAPTCHA is active only when both keys are configured via env vars."""
    return bool(settings.RECAPTCHA_PUBLIC_KEY and settings.RECAPTCHA_PRIVATE_KEY)


def attach_recaptcha(form):
    """Add an invisible reCAPTCHA v3 field to the form when keys are configured.

    Returns the crispy layout elements to splice into the form layout (an empty
    list when reCAPTCHA is disabled, so the form renders exactly as before).
    """
    if not recaptcha_enabled():
        return []
    form.fields["captcha"] = ReCaptchaField(widget=ReCaptchaV3(), label="")
    return [Field("captcha")]


def captcha_passed(form):
    """True when the form has no CAPTCHA field, or the field verified.

    Only meaningful from ``clean()``. Field cleaners run in field order and the
    CAPTCHA is attached LAST, so a ``clean_<field>`` method cannot ask this.

    ``"captcha" in form.cleaned_data`` is the Django-native signal: a field
    whose cleaner raised is removed from ``cleaned_data``. That covers every
    handled failure of ``ReCaptchaField.validate`` — a missing token, an HTTP
    error from Google, an invalid / wrong-action / low-score answer — without
    importing any of them.
    """
    return "captcha" not in form.fields or "captcha" in form.cleaned_data


class UsermodelSignupForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"] = PasswordField(
            label=_("Password"),
            autocomplete="new-password",
        )
        if settings.REQUIRE_TOS_ACCEPTANCE:
            self.fields["tos"] = forms.BooleanField(
                label=_(
                    f"I have read and agree to the "
                    f"<a href='{settings.TOS_LINK}' style='font-weight:bold;'>Terms of Service</a>"
                ),
                widget=forms.CheckboxInput,
            )
        if settings.REQUIRE_DPA_ACCEPTANCE:
            self.fields["dpa"] = forms.BooleanField(
                label=_(
                    f"I have read and agree to the "
                    f"<a href='{settings.DPA_LINK}' style='font-weight:bold;'>Privacy Policy</a>"
                ),
                widget=forms.CheckboxInput,
            )
        self.helper = FormHelper()

        captcha = attach_recaptcha(self)
        self.helper.layout = Layout(
            Field("email", "password1"),
            (
                Field("tos")
                if settings.REQUIRE_TOS_ACCEPTANCE
                else None
            ),
            (
                Field("dpa")
                if settings.REQUIRE_DPA_ACCEPTANCE
                else None
            ),
            *captcha,
            Submit(
                "action",
                _("Sign up"),
                css_class="w-full btn btn-contained btn-primary btn-lg",
            ),
        )

    def clean(self):
        # FIRST, before allauth's clean(): a refused address must already be out
        # of cleaned_data when allauth builds a dummy user from
        # cleaned_data["email"] and validates the password against it — exactly
        # what happened when this check raised from clean_email. Run it after
        # super().clean() and UserAttributeSimilarityValidator gets to compare
        # the password with a refused address and add a second, new error.
        # (Order among the field cleaners is irrelevant here: by the time
        # clean() runs, every field has been cleaned.)
        self._check_deliverability()
        super().clean()
        if settings.REQUIRE_TOS_ACCEPTANCE and not self.cleaned_data.get("tos"):
            self.add_error("tos", _("You must agree to the terms to sign up"))
        if settings.REQUIRE_DPA_ACCEPTANCE and not self.cleaned_data.get("dpa"):
            self.add_error("dpa", _("You must agree to the privacy policy to sign up"))
        return self.cleaned_data

    def _check_deliverability(self):
        """Blocklists and deliverability, from the shared validator — but only
        once the CAPTCHA (if any) has passed.

        This used to be ``clean_email``. A field cleaner runs whether or not the
        CAPTCHA verified, and Django renders every field error together, so the
        page answered "is this domain blocked?" to anyone, token or no token —
        one domain per request rebuilds the whole list. Withholding the verdict
        until the CAPTCHA passed is the only fix; the message is already generic.

        The validator itself lives in ``speedpycom.services.email_deliverability``;
        the other doors that check — team invitations, the public forms, the CSV
        import — call the same thing. See that module for why it fails open on a
        timeout, caches per domain, and is MX-only by default.
        """
        if not captcha_passed(self):
            return
        email = self.cleaned_data.get("email")
        if not email:
            return
        try:
            email_deliverability.validate(email)
        except forms.ValidationError as exc:
            self.add_error("email", exc)


class UsermodelLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        captcha = attach_recaptcha(self)
        self.helper.layout = Layout(
            Field("login", "password"),
            Field("remember"),
            *captcha,
            Submit(
                "action",
                _("Sign in"),
                css_class="w-full btn btn-contained btn-primary btn-lg",
            ),
        )


class UsermodelResetPasswordForm(ResetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        captcha = attach_recaptcha(self)
        self.helper.layout = Layout(
            Field("email"),
            *captcha,
            Submit(
                "action",
                _("Reset password"),
                css_class="w-full btn btn-contained btn-primary btn-lg",
            ),
        )


class UsermodelResetPasswordKeyForm(ResetPasswordKeyForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        captcha = attach_recaptcha(self)
        self.helper.layout = Layout(
            Field("password1", "password2"),
            *captcha,
            Submit(
                "action",
                _("Reset password"),
                css_class="w-full btn btn-contained btn-primary btn-lg",
            ),
        )


class UsermodelChangePasswordForm(ChangePasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("oldpassword", "password1", "password2"),
            Submit("submit", _("Change password"), css_class="btn btn-contained btn-primary"),
        )


class UsermodelAddEmailForm(AddEmailForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("email"),
            Submit("action_add", value=_("Add email"), css_class="btn btn-contained btn-primary"),
        )


class UserProfileForm(forms.ModelForm):
    """Form for editing user profile information."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "profile_picture")
        widgets = {
            "profile_picture": ImageUploadInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("first_name", placeholder="First name"),
            Field("last_name", placeholder="Last name"),
            Field("profile_picture"),
            Submit(
                "submit",
                _("Save changes"),
                css_class="btn btn-contained btn-primary",
            ),
        )


class PersonalAccessTokenForm(forms.Form):
    """Form for creating a personal access token."""

    name = forms.CharField(
        max_length=255,
        help_text=_("A descriptive name for this token, e.g. 'n8n integration'."),
    )
    scopes = forms.MultipleChoiceField(
        choices=(),  # populated dynamically from scope registry
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "checkbox"}),
        help_text=_("Select at least one API scope for this token."),
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "input-outlined"}),
        help_text=_("Optional expiry date. Leave blank for a non-expiring token."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from speedpycom.api.scopes import get_scope_choices

        self.fields["scopes"].choices = get_scope_choices()

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("name"),
            Div(
                Field("scopes"),
                css_class="text-fg [&_label]:text-fg [&_label]:font-normal [&_label]:cursor-pointer",
            ),
            Field("expires_at"),
            Submit(
                "submit",
                _("Create token"),
                css_class="btn btn-contained btn-primary",
            ),
        )

    def clean_scopes(self):
        from speedpycom.api.scopes import validate_scopes

        scopes = self.cleaned_data.get("scopes", [])
        unknown = validate_scopes(scopes)
        if unknown:
            raise forms.ValidationError(
                _("Unknown scope(s): %(scopes)s"),
                params={"scopes": ", ".join(unknown)},
            )
        return scopes
