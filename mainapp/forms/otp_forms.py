from django import forms
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, HTML
from crispy_tailwind.layout import Submit


class OTPSetupVerificationForm(forms.Form):
    """Form to verify TOTP token during setup"""
    token = forms.CharField(
        label=_("Verification Code"),
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'placeholder': '000000',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]{6}',
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            HTML('<p class="mb-4 text-sm text-gray-600">Enter the 6-digit code from your authenticator app.</p>'),
            Field('token'),
            Submit(
                'submit',
                _('Verify and Enable'),
                css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                          "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2"
            ),
        )

    def clean_token(self):
        token = self.cleaned_data['token']
        if not token.isdigit():
            raise forms.ValidationError(_("Verification code must be 6 digits."))
        if len(token) != 6:
            raise forms.ValidationError(_("Verification code must be exactly 6 digits."))
        return token


class OTPTokenForm(forms.Form):
    """Form for OTP token input during login"""
    token = forms.CharField(
        label=_("Verification Code"),
        max_length=12,  # Allow backup codes (longer)
        widget=forms.TextInput(attrs={
            'placeholder': '000000',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'autofocus': True,
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            HTML(
                '<p class="mb-4 text-sm text-gray-600">'
                'Enter the 6-digit code from your authenticator app, or use a backup code.'
                '</p>'
            ),
            Field('token'),
            Submit(
                'submit',
                _('Verify'),
                css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-blue-600 rounded-lg "
                          "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2"
            ),
            HTML(
                '<div class="mt-4 text-sm">'
                '<a href="{% url \'account_login\' %}" class="text-blue-600 hover:text-blue-500">'
                'Cancel and return to login'
                '</a>'
                '</div>'
            ),
        )


class OTPDisableForm(forms.Form):
    """Form to disable OTP (requires password confirmation)"""
    password = forms.CharField(
        label=_("Confirm Password"),
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
        }),
        help_text=_("Enter your password to confirm disabling two-factor authentication.")
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            HTML(
                '<div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">'
                '<p class="text-sm text-red-800 font-semibold">Warning</p>'
                '<p class="text-sm text-red-700 mt-1">'
                'Disabling two-factor authentication will make your account less secure. '
                'All existing devices and backup codes will be deleted.'
                '</p>'
                '</div>'
            ),
            Field('password'),
            Submit(
                'submit',
                _('Disable Two-Factor Authentication'),
                css_class="py-2 px-4 mr-2 text-sm font-medium leading-5 text-white bg-red-600 rounded-lg "
                          "cursor-pointer lg:px-5 lg:py-2 focus:outline-offset-2 hover:bg-red-700"
            ),
            HTML(
                '<div class="mt-4">'
                '<a href="{% url \'account_otp_settings\' %}" '
                'class="text-sm text-gray-600 hover:text-gray-900">'
                'Cancel'
                '</a>'
                '</div>'
            ),
        )

    def clean_password(self):
        password = self.cleaned_data['password']
        if self.user is None:
            raise forms.ValidationError(_("User not specified."))

        # Verify password
        if not self.user.check_password(password):
            raise forms.ValidationError(_("Incorrect password."))

        return password
