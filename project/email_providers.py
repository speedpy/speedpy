"""Email provider selection.

A single ``EMAIL_PROVIDER`` env var selects the concrete email backend that
``django-post_office`` delegates to (the outer ``EMAIL_BACKEND`` stays
``post_office.EmailBackend`` — see ``settings.py``). ``console`` and ``smtp``
use Django's built-in backends; the API providers go through
`django-anymail <https://anymail.dev/>`_, which gives every ESP a consistent
settings shape (``ANYMAIL = {...}``).
"""

from django.core.exceptions import ImproperlyConfigured

# Maps the EMAIL_PROVIDER value to the Django email backend post_office sends through.
EMAIL_PROVIDER_BACKENDS = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "ses": "anymail.backends.amazon_ses.EmailBackend",
    "mailgun": "anymail.backends.mailgun.EmailBackend",
    "sendgrid": "anymail.backends.sendgrid.EmailBackend",
    "postmark": "anymail.backends.postmark.EmailBackend",
    "resend": "anymail.backends.resend.EmailBackend",
}


def resolve_email_backend(provider):
    """Return the email backend dotted path for ``provider``.

    Raises ``ImproperlyConfigured`` for an unknown provider so misconfiguration
    fails loudly at settings import rather than silently dropping email.
    """
    try:
        return EMAIL_PROVIDER_BACKENDS[provider]
    except KeyError:
        valid = ", ".join(sorted(EMAIL_PROVIDER_BACKENDS))
        raise ImproperlyConfigured(
            f"Unknown EMAIL_PROVIDER {provider!r}. Valid values are: {valid}."
        )
