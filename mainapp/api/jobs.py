"""
Async job API — start a demo job (202 Accepted) and poll for status.

Endpoints:
    POST /api/v1/jobs/demo/   — SPEEDPY_DEMO: enqueue a demo job, return 202 + status URL
    GET  /api/v1/jobs/{id}/   — reusable job status polling (keep for production use)
"""

import structlog
from django.db import transaction
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from mainapp.models.jobs import AsyncJob
from speedpycom.api.permissions import HasScope

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class AsyncJobSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    job_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    progress_current = serializers.IntegerField(read_only=True)
    progress_total = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    result = serializers.JSONField(read_only=True)
    error = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    finished_at = serializers.DateTimeField(read_only=True, allow_null=True)


class AsyncJobCreateResponseSerializer(AsyncJobSerializer):
    status_url = serializers.URLField(read_only=True)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class DemoJobCreateView(APIView):
    """Enqueue a demo background job."""

    permission_classes = [HasScope]
    required_scopes = ["write:jobs"]

    @extend_schema(
        tags=["jobs"],
        operation_id="createDemoJob",
        summary="Start a demo background job",
        description=(
            "Enqueue a demo background job that runs for ~10 seconds, progressing "
            "through 5 steps. Returns 202 Accepted with a `status_url` that the "
            "client can poll until the job reaches a terminal state (`succeeded` or "
            "`failed`).\n\n"
            "**Client polling loop:**\n"
            "1. POST to this endpoint to start a job.\n"
            "2. Poll `status_url` every 2-5 seconds.\n"
            "3. Check `status` — continue polling while `queued` or `running`.\n"
            "4. On `succeeded`, read `result`. On `failed`, read `error`.\n"
            "5. Use exponential backoff for production use.\n\n"
            "**Future evolution:** This polling pattern may be complemented or "
            "replaced by Server-Sent Events (SSE) for real-time push updates, "
            "eliminating the need for client-side polling."
        ),
        request=None,
        responses={
            202: AsyncJobCreateResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
        },
        examples=[
            OpenApiExample(
                "Job accepted",
                value={
                    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "job_type": "demo",
                    "status": "queued",
                    "progress_current": 0,
                    "progress_total": 0,
                    "message": "",
                    "result": None,
                    "error": "",
                    "created_at": "2026-06-26T12:00:00Z",
                    "started_at": None,
                    "finished_at": None,
                    "status_url": "https://example.com/api/v1/jobs/a1b2c3d4-e5f6-7890-abcd-ef1234567890/",
                },
                response_only=True,
                status_codes=["202"],
            ),
        ],
    )
    def post(self, request):
        from mainapp.tasks.jobs import run_demo_job

        job = AsyncJob.objects.create(
            owner=request.user,
            job_type="demo",
        )

        transaction.on_commit(lambda pk=str(job.pk): run_demo_job.delay(pk))

        logger.info(
            "api_demo_job_created",
            user_id=str(request.user.id),
            job_id=str(job.id),
        )

        data = AsyncJobSerializer(job).data
        data["status_url"] = request.build_absolute_uri(
            reverse("api:job_status", kwargs={"job_id": job.id})
        )

        return Response(data, status=status.HTTP_202_ACCEPTED)


class JobStatusView(APIView):
    """Poll job status. Only the job owner can view their job."""

    permission_classes = [HasScope]
    required_scopes = ["read:jobs"]

    @extend_schema(
        tags=["jobs"],
        operation_id="getJobStatus",
        summary="Get job status",
        description=(
            "Return the current state of a background job. Only the job owner can "
            "access this endpoint. Poll until `status` is `succeeded` or `failed`."
        ),
        responses={
            200: AsyncJobSerializer,
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Job not found or not owned by you."),
        },
        examples=[
            OpenApiExample(
                "Job running",
                value={
                    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "job_type": "demo",
                    "status": "running",
                    "progress_current": 3,
                    "progress_total": 5,
                    "message": "Processing step 3/5",
                    "result": None,
                    "error": "",
                    "created_at": "2026-06-26T12:00:00Z",
                    "started_at": "2026-06-26T12:00:01Z",
                    "finished_at": None,
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                "Job succeeded",
                value={
                    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "job_type": "demo",
                    "status": "succeeded",
                    "progress_current": 5,
                    "progress_total": 5,
                    "message": "Demo job completed successfully",
                    "result": {
                        "steps_completed": 5,
                        "message": "All steps processed.",
                    },
                    "error": "",
                    "created_at": "2026-06-26T12:00:00Z",
                    "started_at": "2026-06-26T12:00:01Z",
                    "finished_at": "2026-06-26T12:00:11Z",
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, job_id):
        try:
            job = AsyncJob.objects.get(pk=job_id, owner=request.user)
        except AsyncJob.DoesNotExist:
            raise NotFound()

        return Response(AsyncJobSerializer(job).data)
