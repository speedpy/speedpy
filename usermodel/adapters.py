from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.shortcuts import redirect

from django.contrib import messages

from speedpycom.services.email_domains import BLOCKED_EMAIL_MESSAGE, is_blocked
from usermodel.validators import validate_no_url


class CustomAccountAdapter(DefaultAccountAdapter):
    def send_confirmation_mail(self, request, emailconfirmation, signup):
        """
        Override to strip the ``user`` object from the template context so
        confirmation emails cannot include the user's name.

        User-supplied names may contain URLs or other malicious content, and
        embedding them in an email could turn a confirmation message into a
        phishing vector.  The project template already avoids ``{{ user }}``,
        but removing it from the context ensures future template edits cannot
        accidentally re-introduce personalization.
        """
        from allauth.account import app_settings

        # Explicitly shadow "user" so Django's auth context processor
        # (which adds request.user to RequestContext) cannot leak it back.
        ctx = {"user": ""}
        if app_settings.EMAIL_VERIFICATION_BY_CODE_ENABLED:
            ctx["code"] = emailconfirmation.key
        else:
            ctx["key"] = emailconfirmation.key
            ctx["activate_url"] = self.get_email_confirmation_url(
                request, emailconfirmation
            )
        if signup:
            email_template = "account/email/email_confirmation_signup"
        else:
            email_template = "account/email/email_confirmation"
        self.send_mail(
            email_template, emailconfirmation.email_address.email, ctx
        )

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
        if getattr(django_settings, "SPEEDPY_MFA_BACKEND", "django_otp") == "django_otp":
            from django_otp import user_has_device
            if user_has_device(user):
                request.session['otp_pre_auth_user_id'] = str(user.id)
                request.session['otp_pre_auth_backend'] = request.session.get(
                    '_auth_user_backend',
                    'django.contrib.auth.backends.ModelBackend'
                )
                raise ImmediateHttpResponse(redirect(reverse('account_login_otp')))
        return super().login(request, user)

    def pre_social_login(self, request, sociallogin):
        """
        Check for OTP requirement during social login (GitHub, Google, GitLab).
        """
        if getattr(django_settings, "SPEEDPY_MFA_BACKEND", "django_otp") == "django_otp":
            from django_otp import user_has_device
            user = sociallogin.user
            if user.id and user_has_device(user):
                request.session['otp_pre_auth_user_id'] = str(user.id)
                request.session['otp_pre_auth_backend'] = 'allauth.account.auth_backends.AuthenticationBackend'
                raise ImmediateHttpResponse(redirect(reverse('account_login_otp')))


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """Apply the email-domain blocklist to social sign-ups too.

        Without this, the blocklist covers only the password signup form, and
        "Continue with Google" walks straight past it. A Google Workspace domain
        is exactly the kind of domain a project blocks on purpose, so the gap
        matters: the one thing you meant to refuse is the one thing that gets in.

        **New accounts only.** An existing customer is never refused here, even
        if their domain is added to the blocklist later. Three guards, each for
        its own reason:

        * ``sociallogin.is_existing`` — this social account is already linked, so
          this is a returning person signing in. Refusing them would lock a
          paying customer out of their own account because of a list edit.
        * ``request.user.is_authenticated`` — they are connecting a provider from
          account settings, having already proved who they are.
        * an existing ``EmailAddress`` — they already have an account by some
          other route. Blocking their signup is pointless, and any refusal here
          would be the wrong message anyway.

        That mirrors the password path, where the check lives on the signup form
        and the login form does not re-validate the domain. Blocking a domain
        stops new people joining; it is not a way to evict the customers you
        already have.
        """
        super().pre_social_login(request, sociallogin)

        email = (getattr(sociallogin.user, "email", "") or "").strip().lower()
        if not email:
            return
        if sociallogin.is_existing:
            return
        if getattr(request.user, "is_authenticated", False):
            return

        from allauth.account.models import EmailAddress

        if EmailAddress.objects.filter(email__iexact=email).exists():
            return

        if is_blocked(email):
            # The same vague message the signup form uses, deliberately. A
            # wording specific to social sign-in would tell somebody probing the
            # filter which route they got caught on.
            messages.error(request, BLOCKED_EMAIL_MESSAGE)
            raise ImmediateHttpResponse(redirect(reverse("account_login")))

    def populate_user(self, request, sociallogin, data):
        """
        Names coming from social providers (Google, GitHub, GitLab) are
        untrusted and never pass through a form, so they would otherwise
        skip our name validation. Drop any name that contains a URL so it
        can't be injected into outgoing emails (e.g. the confirmation mail).
        """
        user = super().populate_user(request, sociallogin, data)
        for field in ("first_name", "last_name"):
            value = getattr(user, field, "") or ""
            try:
                validate_no_url(value)
            except ValidationError:
                setattr(user, field, "")
        return user
