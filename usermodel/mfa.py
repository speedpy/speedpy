from django.conf import settings


def user_has_totp(user):
    """Return True if the user has an active TOTP authenticator."""
    if not getattr(settings, "SPEEDPY_JWT_REQUIRE_MFA", True):
        return False

    backend = getattr(settings, "SPEEDPY_MFA_BACKEND", "allauth_mfa")

    if backend == "django_otp":
        from django_otp.plugins.otp_totp.models import TOTPDevice

        return TOTPDevice.objects.filter(user=user, confirmed=True).exists()

    if backend == "allauth_mfa":
        try:
            from allauth.mfa.models import Authenticator

            return Authenticator.objects.filter(
                user=user, type=Authenticator.Type.TOTP
            ).exists()
        except ImportError:
            return False

    return False


def verify_totp(user, code):
    """
    Verify a TOTP code for the user. Returns True on success.

    Only accepts TOTP codes, not backup/recovery codes.
    """
    if not code:
        return False

    backend = getattr(settings, "SPEEDPY_MFA_BACKEND", "allauth_mfa")

    if backend == "django_otp":
        from django_otp.plugins.otp_totp.models import TOTPDevice

        for device in TOTPDevice.objects.filter(user=user, confirmed=True):
            if device.verify_token(code):
                return True
        return False

    if backend == "allauth_mfa":
        try:
            from allauth.mfa.models import Authenticator
            from allauth.mfa.totp.internal import auth as totp_auth

            try:
                authenticator = Authenticator.objects.get(
                    user=user, type=Authenticator.Type.TOTP
                )
            except Authenticator.DoesNotExist:
                return False

            instance = authenticator.wrap()
            return instance.validate_code(code)
        except ImportError:
            return False

    return False
