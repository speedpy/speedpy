"""
Idempotency-Key support for unsafe API methods.

Usage — apply the decorator to a DRF view method::

    class MyCreateView(APIView):
        @idempotent
        def post(self, request, ...):
            ...
            return Response(data, status=201)

The decorator intercepts requests that carry an ``Idempotency-Key`` header.

**Reserve-first, not check-then-act.** On first sight it INSERTS an
``IN_PROGRESS`` reservation before running the view. The unique constraint on
``(key, user, method, path)`` is what serialises two concurrent first requests:
under ``ATOMIC_REQUESTS`` the reservation is uncommitted until the request ends,
so a second request with the same key blocks on the unique index until the first
commits or rolls back, then either replays the winner's stored result or — if the
winner discarded its reservation — executes itself.

**Only a returned result is cached.** After the view returns 2xx–4xx the row is
marked ``COMPLETED`` and the response stored. A **raised** exception (DRF turns
``PaymentRequired``/``PermissionDenied``/validation errors into responses *after*
this decorator) or a returned **5xx** deletes the reservation, so the next
attempt runs the view again rather than replaying a non-result.

**Contract (Postgres + ATOMIC_REQUESTS):** the loser of the race may WAIT on the
winner's uncommitted row, then it replays (winner completed) or executes (winner
gone). A committed reservation is therefore always ``COMPLETED`` or absent —
never an observable ``IN_PROGRESS`` from another connection — so there is no
"423/409 in progress" answer in normal operation.
"""

import functools
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from speedpycom.models.idempotency import IdempotencyRecord

IDEMPOTENCY_TTL = getattr(settings, "SPEEDPY_IDEMPOTENCY_TTL_HOURS", 24)
# ASCII only: letters, digits, hyphen, underscore, 1-128 chars. A client that
# wants to use another id (a Zapier trigger id, a form response id) sanitises it
# to this shape first. Matched with fullmatch so a trailing newline is rejected.
_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _reserve(ident, body_hash):
    """Insert an IN_PROGRESS reservation; return it, or None on unique conflict.

    The insert runs in its own savepoint so a losing IntegrityError rolls back
    to here instead of poisoning the request transaction under ATOMIC_REQUESTS.
    """
    try:
        with transaction.atomic():
            return IdempotencyRecord.objects.create(
                **ident,
                request_body_hash=body_hash,
                state=IdempotencyRecord.State.IN_PROGRESS,
                response_status=None,
                response_body=None,
                expires_at=timezone.now() + timedelta(hours=IDEMPOTENCY_TTL),
            )
    except IntegrityError:
        return None


def _replay(record):
    response = Response(record.response_body, status=record.response_status)
    response["Idempotency-Replay"] = "true"
    return response


def _acquire_or_answer(ident, body_hash):
    """Own the reservation, or return the answer for a duplicate.

    Returns an ``IdempotencyRecord`` when the caller should run the view (it now
    holds a fresh reservation), or a ``Response`` (replay or 409) when it should
    not. Re-reserves at most a couple of times to settle a race with a winner
    that vanished or expired.
    """
    reserved = _reserve(ident, body_hash)
    if reserved is not None:
        return reserved

    for _ in range(3):
        record = IdempotencyRecord.objects.filter(**ident).first()
        if record is None:
            # Winner discarded its reservation (raised / 5xx) → try to own it.
            reserved = _reserve(ident, body_hash)
            if reserved is not None:
                return reserved
            continue
        if record.expires_at < timezone.now():
            IdempotencyRecord.objects.filter(pk=record.pk).delete()
            reserved = _reserve(ident, body_hash)
            if reserved is not None:
                return reserved
            continue
        if record.request_body_hash != body_hash:
            return Response(
                {"detail": "Idempotency-Key already used with a different request body."},
                status=status.HTTP_409_CONFLICT,
            )
        if record.state == IdempotencyRecord.State.COMPLETED:
            return _replay(record)
        # Committed IN_PROGRESS is not reachable in this design (see the module
        # docstring); answer defensively rather than risk a duplicate execution.
        return Response(
            {"detail": "A request with this Idempotency-Key is already in progress. Retry shortly."},
            status=status.HTTP_409_CONFLICT,
        )

    # Could neither own the key nor read a settled winner after a few tries.
    return Response(
        {"detail": "A request with this Idempotency-Key is already in progress. Retry shortly."},
        status=status.HTTP_409_CONFLICT,
    )


def idempotent(view_func):
    """Decorator that adds Idempotency-Key support to a DRF view method."""

    @functools.wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        key = request.META.get("HTTP_IDEMPOTENCY_KEY")
        if not key:
            return view_func(self, request, *args, **kwargs)

        if not _KEY_PATTERN.fullmatch(key):
            return Response(
                {"detail": "Invalid Idempotency-Key. Must be 1-128 characters: letters, digits, hyphen, or underscore."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ident = {
            "key": key,
            "user": request.user,
            "method": request.method,
            "path": request.path,
        }
        body_hash = IdempotencyRecord.hash_body(request.body)

        acquired = _acquire_or_answer(ident, body_hash)
        if isinstance(acquired, Response):
            return acquired
        reservation = acquired

        # Run the view inside an inner atomic so a NON-result rolls its writes and
        # on_commit callbacks back with the reservation. A raised exception
        # escapes and rolls the block back automatically (and DRF's handler rolls
        # the request back too); a *returned* 5xx does NOT trigger DRF's
        # set_rollback, so we mark the block for rollback ourselves. Only a
        # returned 2xx-4xx is a cacheable result.
        rolled_back = False
        try:
            with transaction.atomic():
                response = view_func(self, request, *args, **kwargs)
                if not (200 <= response.status_code < 500):
                    transaction.set_rollback(True)
                    rolled_back = True
        except Exception:
            IdempotencyRecord.objects.filter(pk=reservation.pk).delete()
            raise

        if rolled_back:
            # View side effects were discarded; discard the reservation too so a
            # retry executes rather than replaying a non-result.
            IdempotencyRecord.objects.filter(pk=reservation.pk).delete()
            return response

        IdempotencyRecord.objects.filter(pk=reservation.pk).update(
            state=IdempotencyRecord.State.COMPLETED,
            response_status=response.status_code,
            response_body=response.data,
        )
        return response

    return wrapper
