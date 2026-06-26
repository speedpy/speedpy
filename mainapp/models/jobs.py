from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from speedpycom.models import BaseModel


class AsyncJob(BaseModel):
    """
    Tracks the lifecycle of an async background job.

    Each job maps 1:1 to a Celery task invocation. The API returns 202 with
    a status URL; clients poll GET /api/v1/jobs/{id}/ until a terminal state.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")

    TERMINAL_STATUSES = frozenset({Status.SUCCEEDED, Status.FAILED})

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="async_jobs",
    )
    job_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_("Identifier for the kind of work (e.g. 'demo')."),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    progress_current = models.PositiveIntegerField(
        default=0,
        help_text=_("Current step (0-based)."),
    )
    progress_total = models.PositiveIntegerField(
        default=0,
        help_text=_("Total steps; 0 means indeterminate."),
    )
    message = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Human-readable progress message."),
    )
    result = models.JSONField(
        null=True,
        blank=True,
        help_text=_("Arbitrary result payload on success."),
    )
    error = models.TextField(
        blank=True,
        default="",
        help_text=_("Error details on failure."),
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Async Job")
        verbose_name_plural = _("Async Jobs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["job_type"]),
        ]

    def __str__(self):
        return f"{self.job_type} [{self.status}] ({self.id})"

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES
