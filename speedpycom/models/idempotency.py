import hashlib

from django.conf import settings
from django.db import models

from .base import BaseModel


class IdempotencyRecord(BaseModel):
    """Stores the result of an idempotent request for replay.

    Reserve-first: a row is inserted ``IN_PROGRESS`` before the view runs, so the
    unique constraint serialises concurrent first requests with the same key. The
    response is stored and the row marked ``COMPLETED`` only after the view
    returns a result; a raised exception or a 5xx discards the reservation so a
    retry executes rather than replaying a non-result. ``response_status`` and
    ``response_body`` are therefore nullable (an in-progress row has neither).
    """

    class State(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    key = models.CharField(max_length=128)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=512)
    request_body_hash = models.CharField(max_length=64)
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.IN_PROGRESS,
    )
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
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
