from django import forms

from speedpycom.services import email_deliverability
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Div
from crispy_tailwind.layout import Submit

from mainapp.models import Team
from mainapp.timezones import (
    get_default_team_timezone,
    is_valid_timezone,
    tz_choices,
    validate_timezone,
)
from speedpycom.widgets import ImageUploadInput


class TeamCreateForm(forms.ModelForm):
    # Auto-detected from the browser (Intl API) into a hidden field; the server
    # is the authority. LENIENT: blank or invalid falls back to the default,
    # because detection is fallible and must never block team creation.
    timezone = forms.CharField(
        required=False, max_length=64, widget=forms.HiddenInput
    )

    class Meta:
        model = Team
        fields = ('name', 'slug', 'timezone')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False  # We're handling the form tag in the template
        self.helper.layout = Layout(
            Field('name', placeholder='My Team'),
            Field('slug', placeholder='my-team'),
            Field('timezone'),  # hidden; filled by the create page's Intl script
        )

    def clean_timezone(self):
        value = (self.cleaned_data.get('timezone') or '').strip()
        return value if is_valid_timezone(value) else get_default_team_timezone()


class InviteMemberForm(forms.Form):
    """Form for inviting a new team member"""

    email = forms.EmailField(
        label='Email Address',
        max_length=255,
        help_text='Enter the email address of the person you want to invite',
        widget=forms.EmailInput(attrs={'placeholder': 'colleague@example.com'})
    )

    role = forms.ChoiceField(
        label='Role',
        choices=[
            ('viewer', 'Viewer - Read-only access'),
            ('member', 'Member - Create and edit'),
            ('admin', 'Admin - Manage team and members'),
        ],
        initial='member'
    )

    message = forms.CharField(
        label='Personal Message (Optional)',
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Add a personal message...'
        })
    )

    def __init__(self, *args, team=None, inviter_membership=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.inviter_membership = inviter_membership

        # Crispy forms helper
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Div(
                Field('email', css_class='mb-4'),
                Field('role', css_class='mb-4'),
                Field('message', css_class='mb-4'),
                css_class='space-y-4'
            )
        )

        # Adjust role choices based on inviter's role
        if inviter_membership and inviter_membership.role == 'admin':
            self.fields['role'].choices = [
                ('viewer', 'Viewer - Read-only access'),
                ('member', 'Member - Create and edit'),
            ]

    def clean_email(self):
        """Validate email and check for existing membership"""
        from django.contrib.auth import get_user_model
        from mainapp.models import TeamInvitation, TeamMembership
        from django.utils import timezone

        email = self.cleaned_data['email'].strip().lower()

        # Deliverability BEFORE the membership lookups: an invitation is a piece
        # of mail, so an address we cannot deliver to is not an invitation, it is
        # a bounce charged against the SES account. Same validator signup uses
        # (speedpycom.services.email_deliverability), which is the whole point —
        # the check used to exist on signup alone.
        email_deliverability.validate(email)

        # Check if user already has membership
        User = get_user_model()
        user = User.objects.filter(email=email).first()
        if user:
            if TeamMembership.objects.filter(team=self.team, user=user).exists():
                raise forms.ValidationError("This user is already a member of the team")

        # Check for pending invitation
        if TeamInvitation.objects.filter(
            team=self.team,
            email=email,
            status='pending',
            expires_at__gt=timezone.now()
        ).exists():
            raise forms.ValidationError("An invitation has already been sent to this email")

        return email


class UpdateMemberRoleForm(forms.Form):
    """Form for updating a team member's role"""

    role = forms.ChoiceField(
        label='Role',
        choices=[
            ('viewer', 'Viewer'),
            ('member', 'Member'),
            ('admin', 'Admin'),
            ('owner', 'Owner'),
        ]
    )

    def __init__(self, *args, membership=None, current_user_membership=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership
        self.current_user_membership = current_user_membership

        # Crispy forms helper
        self.helper = FormHelper()
        self.helper.form_tag = False

        if membership:
            self.fields['role'].initial = membership.role

        # Filter choices based on current user's role
        if current_user_membership:
            if current_user_membership.role == 'admin':
                # Admins can only assign member/viewer roles
                self.fields['role'].choices = [
                    ('viewer', 'Viewer'),
                    ('member', 'Member'),
                ]
            elif current_user_membership.role != 'owner':
                # Non-owners/admins shouldn't access this form
                self.fields['role'].choices = []


class TeamSettingsForm(forms.ModelForm):
    """Form for updating team settings (name, slug, logo, timezone)."""

    class Meta:
        model = Team
        fields = ('name', 'slug', 'logo', 'timezone')
        widgets = {
            'logo': ImageUploadInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # An explicit dropdown from the shortlist. STRICT: the value comes from
        # our own menu, so ChoiceField already rejects anything not offered; an
        # invalid value is a tampered POST. `include` keeps the team's current
        # value selectable even if it is off the shortlist.
        current = getattr(self.instance, 'timezone', '') or ''
        self.fields['timezone'] = forms.ChoiceField(
            choices=tz_choices(include=current),
            required=True,
            initial=current or None,
            help_text='Used for send scheduling and daily send caps.',
        )
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Div(
                Field('name', placeholder='My Team'),
                Field('slug', placeholder='my-team',
                      css_class='font-mono',
                      help_text='URL-friendly identifier for your team'),
                Field('logo'),
                Field('timezone'),
                css_class='space-y-4'
            )
        )

    def clean_slug(self):
        """Ensure slug is unique, excluding current instance."""
        slug = self.cleaned_data['slug']
        existing = Team.objects.filter(slug=slug).exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("This slug is already taken. Please choose another.")
        return slug

    def clean_timezone(self):
        """Strict: reject a value that is not a resolvable IANA zone (a tampered
        POST, or a bad value the team had stored)."""
        value = self.cleaned_data['timezone']
        validate_timezone(value)
        return value

    def clean_logo(self):
        """Downscale the logo to 256px and convert it to a web-native format:
        HEIC/HEIF photos otherwise do not render in Firefox/Chrome, and a
        full-resolution upload is wasteful for something shown at a few dozen
        pixels. See speedpycom.images."""
        logo = self.cleaned_data.get('logo')
        if not logo or not hasattr(logo, 'read'):
            return logo  # unchanged / cleared / existing stored file
        from speedpycom.images import prepare_image

        return prepare_image(logo, 256)