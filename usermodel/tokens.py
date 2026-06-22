from django.conf import settings


def email_verified(user):
    """
    Return True if the user has a verified primary email address.

    Checks the allauth EmailAddress table first, falling back to
    User.is_email_confirmed for callers that cannot import allauth.
    """
    if not getattr(settings, "SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL", True):
        return True

    try:
        from allauth.account.models import EmailAddress

        if EmailAddress.objects.filter(user=user, primary=True, verified=True).exists():
            return True
    except ImportError:
        pass

    return user.is_email_confirmed
