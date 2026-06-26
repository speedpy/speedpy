from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from usermodel.models import ApiAccessLog, PersonalAccessToken, _truncate_ip

User = get_user_model()

ME_URL = "/api/v1/me/"


def _make_user(email="audit@example.com"):
    return User.objects.create_user(email=email, password="testpass123")


class TruncateIPTests(TestCase):
    def test_ipv4(self):
        self.assertEqual(_truncate_ip("192.168.1.42"), "192.168.1.0")

    def test_ipv6(self):
        result = _truncate_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        self.assertEqual(result, "2001:db8:85a3::")

    def test_ipv6_compressed(self):
        result = _truncate_ip("fe80::abcd:ef12")
        self.assertEqual(result, "fe80::")

    def test_invalid_ip(self):
        self.assertEqual(_truncate_ip("not-an-ip"), "")

    def test_empty(self):
        self.assertEqual(_truncate_ip(""), "")

    def test_none(self):
        self.assertEqual(_truncate_ip(None), "")


class AuditLogDisabledTests(TestCase):
    """With the default setting (disabled), no audit rows are created."""

    def test_no_log_when_disabled(self):
        user = _make_user()
        _pat, raw = PersonalAccessToken.create_token(user, "t1", scopes=["read:profile"])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        client.get(ME_URL)
        self.assertEqual(ApiAccessLog.objects.count(), 0)


@override_settings(SPEEDPY_API_ACCESS_LOG_ENABLED=True)
class AuditLogEnabledTests(TestCase):
    """With audit logging enabled, API requests create bounded records."""

    def setUp(self):
        self.user = _make_user()
        self.pat, self.raw_token = PersonalAccessToken.create_token(
            self.user, "audit-test", scopes=["read:profile"]
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")

    def test_creates_log_entry(self):
        response = self.client.get(ME_URL)
        self.assertEqual(ApiAccessLog.objects.count(), 1)
        log = ApiAccessLog.objects.first()
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.method, "GET")
        self.assertEqual(log.path, ME_URL)
        self.assertEqual(log.status_code, response.status_code)
        self.assertEqual(log.token_type, "pat")
        self.assertEqual(log.token_id, str(self.pat.id))
        self.assertEqual(log.scopes, ["read:profile"])

    def test_no_raw_token_in_log(self):
        self.client.get(ME_URL)
        log = ApiAccessLog.objects.first()
        self.assertNotIn("spd_", log.token_id)

    def test_ip_is_truncated(self):
        self.client.get(ME_URL, REMOTE_ADDR="10.20.30.40")
        log = ApiAccessLog.objects.first()
        self.assertEqual(log.ip_truncated, "10.20.30.0")

    def test_non_api_path_not_logged(self):
        """Requests outside /api/ should not be logged."""
        self.client.get("/accounts/login/")
        self.assertEqual(ApiAccessLog.objects.count(), 0)

    def test_pat_last_used_still_updated(self):
        """PAT record_usage() baseline must still work."""
        self.assertIsNone(self.pat.last_used_at)
        self.client.get(ME_URL)
        self.pat.refresh_from_db()
        self.assertIsNotNone(self.pat.last_used_at)

    def test_unauthenticated_request_logged(self):
        """Anonymous API requests should still be logged."""
        anon = APIClient()
        anon.get(ME_URL)
        self.assertEqual(ApiAccessLog.objects.count(), 1)
        log = ApiAccessLog.objects.first()
        self.assertIsNone(log.user)
        self.assertEqual(log.token_type, "")

    def test_admin_readonly(self):
        """ApiAccessLogAdmin should disallow add and change."""
        from usermodel.admin import ApiAccessLogAdmin
        from django.contrib.admin.sites import AdminSite

        admin = ApiAccessLogAdmin(ApiAccessLog, AdminSite())
        self.assertFalse(admin.has_add_permission(None))
        self.assertFalse(admin.has_change_permission(None))
