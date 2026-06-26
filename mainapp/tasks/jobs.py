import time

import structlog
from celery import shared_task
from django.utils import timezone

from mainapp.models.jobs import AsyncJob

logger = structlog.get_logger(__name__)

DEMO_STEPS = 5
DEMO_STEP_DELAY = 2  # seconds


@shared_task(bind=True, name="run_demo_job", acks_late=True)
def run_demo_job(self, job_id: str):
    """
    Demo long-running task that progresses through several steps.

    Updates the AsyncJob record at each step so clients can poll for progress.
    """
    try:
        job = AsyncJob.objects.get(pk=job_id)
    except AsyncJob.DoesNotExist:
        logger.warning("demo_job_not_found", job_id=job_id)
        return

    if job.is_terminal:
        logger.info("demo_job_already_terminal", job_id=job_id, status=job.status)
        return

    job.status = AsyncJob.Status.RUNNING
    job.started_at = timezone.now()
    job.progress_total = DEMO_STEPS
    job.message = "Starting demo job"
    job.save(update_fields=[
        "status", "started_at", "progress_total", "message", "updated_at",
    ])

    logger.info("demo_job_started", job_id=job_id)

    try:
        for step in range(1, DEMO_STEPS + 1):
            time.sleep(DEMO_STEP_DELAY)

            job.progress_current = step
            job.message = f"Processing step {step}/{DEMO_STEPS}"
            job.save(update_fields=["progress_current", "message", "updated_at"])

            logger.info(
                "demo_job_progress",
                job_id=job_id,
                step=step,
                total=DEMO_STEPS,
            )

        job.status = AsyncJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.message = "Demo job completed successfully"
        job.result = {
            "steps_completed": DEMO_STEPS,
            "message": "All steps processed.",
        }
        job.save(update_fields=[
            "status", "finished_at", "message", "result", "updated_at",
        ])

        logger.info("demo_job_succeeded", job_id=job_id)

    except Exception as exc:
        job.status = AsyncJob.Status.FAILED
        job.finished_at = timezone.now()
        job.message = "Demo job failed"
        job.error = str(exc)
        job.save(update_fields=[
            "status", "finished_at", "message", "error", "updated_at",
        ])

        logger.error("demo_job_failed", job_id=job_id, error=str(exc))
