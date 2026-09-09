"""Reserve-first behaviour of the @idempotent decorator (speedpycom).

The HTTP contract (replay, 409 on a different body, per-user namespacing) is
covered end-to-end by test_api_idempotency. These tests drive the decorator
directly to exercise the branches an ordinary create endpoint cannot easily
reach: a raised exception and a 5xx must DISCARD the reservation (so a retry
executes), and an expired record must be replaced.
"""

import types
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from speedpycom.api.idempotency import idempotent
from speedpycom.models.idempotency import IdempotencyRecord
from usermodel.models import User

BODY = b'{"a":1}'
BODY_HASH = IdempotencyRecord.hash_body(BODY)


class DecoratorReserveFirstTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="x")

    def _req(self, key="key-123", body=BODY):
        return types.SimpleNamespace(
            user=self.user,
            method="POST",
            path="/api/v1/things/",
            body=body,
            META={"HTTP_IDEMPOTENCY_KEY": key},
        )

    def _ident(self, key="key-123"):
        return dict(key=key, user=self.user, method="POST", path="/api/v1/things/")

    def test_no_key_runs_view_and_stores_nothing(self):
        calls = []

        @idempotent
        def view(self_, request):
            calls.append(1)
            return Response({"ok": True}, status=201)

        req = self._req()
        del req.META["HTTP_IDEMPOTENCY_KEY"]
        resp = view(None, req)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(calls, [1])
        self.assertFalse(IdempotencyRecord.objects.exists())

    def test_invalid_key_400(self):
        @idempotent
        def view(self_, request):
            return Response({"ok": True}, status=201)

        resp = view(None, self._req(key="not a valid key!"))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(IdempotencyRecord.objects.exists())

    def test_unicode_key_rejected(self):
        @idempotent
        def view(self_, request):
            return Response({"ok": True}, status=201)

        resp = view(None, self._req(key="clé-café"))
        self.assertEqual(resp.status_code, 400)

    def test_success_stores_completed(self):
        @idempotent
        def view(self_, request):
            return Response({"id": 7}, status=201)

        resp = view(None, self._req())
        self.assertEqual(resp.status_code, 201)
        rec = IdempotencyRecord.objects.get(**self._ident())
        self.assertEqual(rec.state, IdempotencyRecord.State.COMPLETED)
        self.assertEqual(rec.response_status, 201)
        self.assertEqual(rec.response_body, {"id": 7})

    def _side_effect(self):
        """A view-side DB write that must roll back with a non-result."""
        return IdempotencyRecord.objects.create(
            key="side-effect", user=self.user, method="X", path="/y/",
            request_body_hash="z", state=IdempotencyRecord.State.COMPLETED,
            response_status=200, response_body={}, expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_raised_exception_rolls_back_reservation_and_side_effects(self):
        calls = []

        @idempotent
        def view(self_, request):
            calls.append(1)
            self._side_effect()  # a DB write the view made before failing
            raise PermissionDenied("nope")

        with self.assertRaises(PermissionDenied):
            view(None, self._req())
        # Both the reservation AND the view's write are gone → a retry executes.
        self.assertFalse(IdempotencyRecord.objects.filter(**self._ident()).exists())
        self.assertFalse(IdempotencyRecord.objects.filter(key="side-effect").exists())
        self.assertEqual(calls, [1])

    def test_returned_5xx_rolls_back_reservation_and_side_effects(self):
        @idempotent
        def view(self_, request):
            self._side_effect()  # a DB write the view made before returning 5xx
            return Response({"detail": "boom"}, status=500)

        resp = view(None, self._req())
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(IdempotencyRecord.objects.filter(**self._ident()).exists())
        self.assertFalse(IdempotencyRecord.objects.filter(key="side-effect").exists())

    def test_completed_record_replays_without_running_view(self):
        IdempotencyRecord.objects.create(
            **self._ident(),
            request_body_hash=BODY_HASH,
            state=IdempotencyRecord.State.COMPLETED,
            response_status=201,
            response_body={"id": 99},
            expires_at=timezone.now() + timedelta(hours=1),
        )
        calls = []

        @idempotent
        def view(self_, request):
            calls.append(1)
            return Response({"id": "new"}, status=201)

        resp = view(None, self._req())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data, {"id": 99})
        self.assertEqual(resp["Idempotency-Replay"], "true")
        self.assertEqual(calls, [])  # view not run

    def test_different_body_same_key_409(self):
        IdempotencyRecord.objects.create(
            **self._ident(),
            request_body_hash="deadbeef",
            state=IdempotencyRecord.State.COMPLETED,
            response_status=201,
            response_body={"id": 1},
            expires_at=timezone.now() + timedelta(hours=1),
        )

        @idempotent
        def view(self_, request):
            return Response({"id": "new"}, status=201)

        resp = view(None, self._req())
        self.assertEqual(resp.status_code, 409)

    def test_expired_record_is_replaced_and_view_runs(self):
        IdempotencyRecord.objects.create(
            **self._ident(),
            request_body_hash=BODY_HASH,
            state=IdempotencyRecord.State.COMPLETED,
            response_status=201,
            response_body={"id": "old"},
            expires_at=timezone.now() - timedelta(hours=1),
        )
        calls = []

        @idempotent
        def view(self_, request):
            calls.append(1)
            return Response({"id": "fresh"}, status=201)

        resp = view(None, self._req())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data, {"id": "fresh"})
        self.assertEqual(calls, [1])
        rec = IdempotencyRecord.objects.get(**self._ident())
        self.assertEqual(rec.response_body, {"id": "fresh"})

    def test_committed_in_progress_answers_conflict(self):
        # Not reachable cross-connection in normal operation, but the defensive
        # branch must not run the view or replay a non-result.
        IdempotencyRecord.objects.create(
            **self._ident(),
            request_body_hash=BODY_HASH,
            state=IdempotencyRecord.State.IN_PROGRESS,
            response_status=None,
            response_body=None,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        calls = []

        @idempotent
        def view(self_, request):
            calls.append(1)
            return Response({"id": "new"}, status=201)

        resp = view(None, self._req())
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(calls, [])
