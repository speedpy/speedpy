from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from mainapp.models import AsyncJob
from usermodel.models import User


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class JobAPITestBase(TestCase):
    """Shared setup for job API tests."""

    def setUp(self):
        self.client = APIClient()

        self.user_a = User.objects.create_user(
            email="alice@example.com", password="pass123"
        )
        self.user_b = User.objects.create_user(
            email="bob@example.com", password="pass123"
        )


class DemoJobCreateTests(JobAPITestBase):
    def test_anonymous_rejected(self):
        response = self.client.post("/api/v1/jobs/demo/")
        self.assertIn(response.status_code, [401, 403])

    @patch("mainapp.tasks.jobs.run_demo_job.delay")
    def test_creates_job_returns_202(self, mock_delay):
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post("/api/v1/jobs/demo/")
        self.assertEqual(response.status_code, 202)

        data = response.data
        self.assertEqual(data["job_type"], "demo")
        self.assertEqual(data["status"], "queued")
        self.assertIn("status_url", data)
        self.assertIn(str(data["id"]), data["status_url"])

        # Job was persisted
        self.assertTrue(AsyncJob.objects.filter(pk=data["id"]).exists())

    @patch("mainapp.tasks.jobs.run_demo_job.delay")
    def test_response_field_contract(self, mock_delay):
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post("/api/v1/jobs/demo/")
        expected_fields = {
            "id", "job_type", "status", "progress_current", "progress_total",
            "message", "result", "error", "created_at", "started_at",
            "finished_at", "status_url",
        }
        self.assertEqual(set(response.data.keys()), expected_fields)


class JobStatusTests(JobAPITestBase):
    def setUp(self):
        super().setUp()
        self.job = AsyncJob.objects.create(
            owner=self.user_a,
            job_type="demo",
        )

    def test_anonymous_rejected(self):
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        self.assertIn(response.status_code, [401, 403])

    def test_owner_can_view(self):
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.job.id))
        self.assertEqual(response.data["status"], "queued")

    def test_non_owner_gets_404(self):
        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_job_404(self):
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)

    def test_status_field_contract(self):
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        expected_fields = {
            "id", "job_type", "status", "progress_current", "progress_total",
            "message", "result", "error", "created_at", "started_at",
            "finished_at",
        }
        self.assertEqual(set(response.data.keys()), expected_fields)

    def test_reflects_progress(self):
        self.job.status = AsyncJob.Status.RUNNING
        self.job.progress_current = 3
        self.job.progress_total = 5
        self.job.message = "Processing step 3/5"
        self.job.save()

        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        self.assertEqual(response.data["status"], "running")
        self.assertEqual(response.data["progress_current"], 3)
        self.assertEqual(response.data["progress_total"], 5)

    def test_reflects_success(self):
        self.job.status = AsyncJob.Status.SUCCEEDED
        self.job.result = {"steps_completed": 5}
        self.job.save()

        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(response.data["result"], {"steps_completed": 5})

    def test_reflects_failure(self):
        self.job.status = AsyncJob.Status.FAILED
        self.job.error = "Something went wrong"
        self.job.save()

        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f"/api/v1/jobs/{self.job.id}/")
        self.assertEqual(response.data["status"], "failed")
        self.assertEqual(response.data["error"], "Something went wrong")


class DemoTaskTests(JobAPITestBase):
    """Test the Celery task logic directly (eager mode)."""

    def test_success_flow(self):
        job = AsyncJob.objects.create(
            owner=self.user_a,
            job_type="demo",
        )

        from mainapp.tasks.jobs import run_demo_job, DEMO_STEPS

        # Patch sleep to avoid actual delays in tests
        with patch("mainapp.tasks.jobs.time.sleep"):
            run_demo_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, AsyncJob.Status.SUCCEEDED)
        self.assertEqual(job.progress_current, DEMO_STEPS)
        self.assertEqual(job.progress_total, DEMO_STEPS)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)
        self.assertIsNotNone(job.result)

    def test_skips_terminal_job(self):
        job = AsyncJob.objects.create(
            owner=self.user_a,
            job_type="demo",
            status=AsyncJob.Status.SUCCEEDED,
        )

        from mainapp.tasks.jobs import run_demo_job

        with patch("mainapp.tasks.jobs.time.sleep"):
            run_demo_job(str(job.pk))

        job.refresh_from_db()
        # Should remain succeeded, not re-run
        self.assertEqual(job.status, AsyncJob.Status.SUCCEEDED)

    def test_failure_flow(self):
        job = AsyncJob.objects.create(
            owner=self.user_a,
            job_type="demo",
        )

        from mainapp.tasks.jobs import run_demo_job

        with patch("mainapp.tasks.jobs.time.sleep", side_effect=RuntimeError("boom")):
            run_demo_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, AsyncJob.Status.FAILED)
        self.assertIn("boom", job.error)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)

    def test_nonexistent_job(self):
        from mainapp.tasks.jobs import run_demo_job

        # Should not raise
        run_demo_job("00000000-0000-0000-0000-000000000000")
