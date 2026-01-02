from allauth.account.adapter import DefaultAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from django.urls import reverse
from django.shortcuts import redirect
from django_otp import user_has_device


class CustomAccountAdapter(DefaultAccountAdapter):
    def send_account_already_exists_mail(self, *args, **kwargs):
        """
        We don't need this feature ever. Nobody wants it. I swear.
        """
        pass

    def login(self, request, user):
        """
        Override login to check if user has OTP enabled.
        If yes, don't complete login yet - redirect to OTP input page.
        """
        # Check if user has OTP devices
        if user_has_device(user):
            # Store user ID in session for OTP verification
            request.session['otp_pre_auth_user_id'] = str(user.id)
            request.session['otp_pre_auth_backend'] = request.session.get(
                '_auth_user_backend',
                'django.contrib.auth.backends.ModelBackend'
            )
            # Raise ImmediateHttpResponse to interrupt the flow
            raise ImmediateHttpResponse(redirect(reverse('account_login_otp')))
        else:
            # No OTP required, proceed with normal login
            return super().login(request, user)

    def pre_social_login(self, request, sociallogin):
        """
        Check for OTP requirement during social login (GitHub, Google, GitLab).
        """
        user = sociallogin.user
        if user.id and user_has_device(user):
            # Store in session and redirect to OTP
            request.session['otp_pre_auth_user_id'] = str(user.id)
            request.session['otp_pre_auth_backend'] = 'allauth.account.auth_backends.AuthenticationBackend'
            # Raise ImmediateHttpResponse to interrupt the flow
            raise ImmediateHttpResponse(redirect(reverse('account_login_otp')))
