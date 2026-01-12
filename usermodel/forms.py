from allauth.account.forms import SignupForm, PasswordField, LoginForm, ResetPasswordForm, ResetPasswordKeyForm, \
    ChangePasswordForm, AddEmailForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field
from crispy_tailwind.layout import Submit
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

# Import ReCaptcha only if credentials are configured
RECAPTCHA_ENABLED = bool(settings.RECAPTCHA_PUBLIC_KEY and settings.RECAPTCHA_PRIVATE_KEY)
if RECAPTCHA_ENABLED:
    from django_recaptcha.fields import ReCaptchaField
    from django_recaptcha.widgets import ReCaptchaV3


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
                    f"<a href='{settings.TOS_LINK}' style='font-weight:bold;'>Terms of Service</a>"),
                widget=forms.CheckboxInput,
            )
        if settings.REQUIRE_DPA_ACCEPTANCE:
            self.fields["dpa"] = forms.BooleanField(
                label=_(
                    f"I have read and agree to the "
                    f"<a href='{settings.DPA_LINK}' style='font-weight:bold;'>Privacy Policy</a>"),
                widget=forms.CheckboxInput,
            )

        # Add reCAPTCHA v3 field if credentials are configured
        if RECAPTCHA_ENABLED:
            self.fields["captcha"] = ReCaptchaField(
                widget=ReCaptchaV3(
                    attrs={
                        'required_score': settings.RECAPTCHA_REQUIRED_SCORE,
                    }
                ),
                label=''
            )

        self.helper = FormHelper()

        # Build layout fields dynamically
        layout_fields = [
            Field("email", "password1"),
            Field(
                "tos",
                template="components/forms/boolean_field.html") if settings.REQUIRE_TOS_ACCEPTANCE else None,
            Field(
                "dpa",
                template="components/forms/boolean_field.html") if settings.REQUIRE_DPA_ACCEPTANCE else None,
        ]

        # Add captcha field to layout if enabled
        if RECAPTCHA_ENABLED:
            layout_fields.append(Field("captcha"))

        # Add submit button
        layout_fields.append(
            Submit("submit", _("Sign up"),
                   css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                             "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2")
        )

        self.helper.layout = Layout(*layout_fields)

    def clean(self):
        super().clean()
        if settings.REQUIRE_TOS_ACCEPTANCE and not self.cleaned_data.get("tos"):
            self.add_error("tos", _("You must agree to the terms to sign up"))
        if settings.REQUIRE_DPA_ACCEPTANCE and not self.cleaned_data.get("dpa"):
            self.add_error("dpa", _("You must agree to the privacy policy to sign up"))
        return self.cleaned_data


class UsermodelLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add reCAPTCHA v3 field if credentials are configured
        if RECAPTCHA_ENABLED:
            self.fields["captcha"] = ReCaptchaField(
                widget=ReCaptchaV3(
                    attrs={
                        'required_score': settings.RECAPTCHA_REQUIRED_SCORE,
                    }
                ),
                label=''
            )

        self.helper = FormHelper()

        # Build layout fields dynamically
        layout_fields = [
            Field("login", "password"),
            Field(
                "remember",
                template="components/forms/boolean_field.html"),
        ]

        # Add captcha field to layout if enabled
        if RECAPTCHA_ENABLED:
            layout_fields.append(Field("captcha"))

        # Add submit button
        layout_fields.append(
            Submit("submit", _("Sign in"),
                   css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                             "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2")
        )

        self.helper.layout = Layout(*layout_fields)


class UsermodelResetPasswordForm(ResetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add reCAPTCHA v3 field if credentials are configured
        if RECAPTCHA_ENABLED:
            self.fields["captcha"] = ReCaptchaField(
                widget=ReCaptchaV3(
                    attrs={
                        'required_score': settings.RECAPTCHA_REQUIRED_SCORE,
                    }
                ),
                label=''
            )

        self.helper = FormHelper()

        # Build layout fields dynamically
        layout_fields = [Field("email")]

        # Add captcha field to layout if enabled
        if RECAPTCHA_ENABLED:
            layout_fields.append(Field("captcha"))

        # Add submit button
        layout_fields.append(
            Submit("submit", _("Reset password"),
                   css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                             "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2")
        )

        self.helper.layout = Layout(*layout_fields)


class UsermodelResetPasswordKeyForm(ResetPasswordKeyForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("password1", "password2"),
            Submit("submit", _("Reset password"),
                   css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                             "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2"),
        )


class UsermodelChangePasswordForm(ChangePasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("oldpassword", "password1", "password2"),
            Submit("submit", _("Change password"),
                   css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                             "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2"),
        )


class UsermodelAddEmailForm(AddEmailForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("email"),
            Submit("action_add",
                   value=_("Add email"),
                   css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                             "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2"),
        )
