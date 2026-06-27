"""Signed account references for checkout metadata.

Paddle checkout runs client-side, so any value we put in ``custom_data`` (incl.
the billable account id/type) can be tampered with in the browser before the
checkout opens. To make webhook account resolution trustworthy, the billable
reference is wrapped in a server-signed token (HMAC via ``SECRET_KEY``) at
checkout time and verified in the webhook. The raw, human-readable billable
fields may still be sent for debugging, but only the verified token is trusted to
resolve the account.
"""

from django.core import signing

_SALT = "mainapp.billing.account"


def sign_account(billable_type, billable_id):
    """Return a signed token binding a billable type+id to our server."""
    return signing.dumps({"t": billable_type, "id": str(billable_id)}, salt=_SALT)


def unsign_account(token):
    """Return ``(billable_type, billable_id)`` from a token, or ``(None, None)``.

    Fails closed: a missing, malformed, or tampered token yields ``(None, None)``
    so the webhook skips applying the event rather than trusting forged data.
    """
    if not token:
        return None, None
    try:
        data = signing.loads(token, salt=_SALT)
    except signing.BadSignature:
        return None, None
    return data.get("t"), data.get("id")
