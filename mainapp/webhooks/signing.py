import hashlib
import hmac


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """Compute HMAC-SHA256 hex digest of ``timestamp.body`` using *secret*."""
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """Return True if *signature* matches the expected HMAC-SHA256 digest."""
    expected = sign(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)
