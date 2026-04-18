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
from crispy_forms.layout import Layout, Field

from crispy_tailwind.layout import Submit
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from usermodel.models import User


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
            Submit(
                "submit",
                _("Sign up"),
                css_class="w-full px-6 py-[11px] text-[15px] font-semibold leading-[26px] text-gray-900 "
                "bg-[#7582EB] hover:bg-[#646fd4] rounded-lg cursor-pointer focus:outline-offset-2",
            ),
        )

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
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("login", "password"),
            Field("remember"),
            Submit(
                "submit",
                _("Sign in"),
                css_class="w-full px-6 py-[11px] text-[15px] font-semibold leading-[26px] text-gray-900 "
                "bg-[#7582EB] hover:bg-[#646fd4] rounded-lg cursor-pointer focus:outline-offset-2",
            ),
        )


class UsermodelResetPasswordForm(ResetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("email"),
            Submit(
                "submit",
                _("Reset password"),
                css_class="w-full px-6 py-[11px] text-[15px] font-semibold leading-[26px] text-gray-900 "
                "bg-[#7582EB] hover:bg-[#646fd4] rounded-lg cursor-pointer focus:outline-offset-2",
            ),
        )


class UsermodelResetPasswordKeyForm(ResetPasswordKeyForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("password1", "password2"),
            Submit(
                "submit",
                _("Reset password"),
                css_class="w-full px-6 py-[11px] text-[15px] font-semibold leading-[26px] text-gray-900 "
                "bg-[#7582EB] hover:bg-[#646fd4] rounded-lg cursor-pointer focus:outline-offset-2",
            ),
        )


class UsermodelChangePasswordForm(ChangePasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("oldpassword", "password1", "password2"),
            Submit("submit", _("Change password")),
        )


class UsermodelAddEmailForm(AddEmailForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field("email"),
            Submit("action_add", value=_("Add email")),
        )


class UserProfileForm(forms.ModelForm):
    """Form for editing user profile information."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "profile_picture")
        widgets = {
            "profile_picture": forms.FileInput(attrs={"accept": "image/*"}),
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
                css_class="w-full px-6 py-[11px] text-[15px] font-semibold leading-[26px] text-gray-900 "
                "bg-[#7582EB] hover:bg-[#646fd4] rounded-lg cursor-pointer focus:outline-offset-2",
            ),
        )
