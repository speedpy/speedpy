import hashlib

from django.conf import settings
from django.db import models

from .base import BaseModel


class IdempotencyRecord(BaseModel):
    """Stores the result of an idempotent request for replay."""

    key = models.CharField(max_length=128)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=512)
    request_body_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key", "user", "method", "path"],
                name="unique_idempotency_key",
            ),
        ]

    @staticmethod
    def hash_body(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()
