from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Div
from crispy_tailwind.layout import Submit

from mainapp.models import Team


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ('name', 'slug',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False  # We're handling the form tag in the template
        self.helper.layout = Layout(
            Field('name', placeholder='My Team'),
            Field('slug', placeholder='my-team'),
        )


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
    """Form for updating team settings (name, slug, logo)."""

    class Meta:
        model = Team
        fields = ('name', 'slug', 'logo')
        widgets = {
            'logo': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'block w-full text-sm text-gray-900 border border-gray-300 rounded-lg cursor-pointer bg-gray-50'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Div(
                Field('name', placeholder='My Team'),
                Field('slug', placeholder='my-team',
                      css_class='font-mono',
                      help_text='URL-friendly identifier for your team'),
                Field('logo'),
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