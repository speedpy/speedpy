"""
Idempotency-Key support for unsafe API methods.

Usage — apply the decorator to a DRF view method::

    class MyCreateView(APIView):
        @idempotent
        def post(self, request, ...):
            ...
            return Response(data, status=201)

The decorator intercepts requests that carry an ``Idempotency-Key`` header.
On first sight it stores the response; on replay it returns the stored
response without re-executing the view.  If the same key is reused with a
different request body, a 409 Conflict is returned.
"""

import functools
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from speedpycom.models.idempotency import IdempotencyRecord

IDEMPOTENCY_TTL = getattr(settings, "SPEEDPY_IDEMPOTENCY_TTL_HOURS", 24)
_KEY_PATTERN = re.compile(r"^[\w\-]{1,128}$")


def idempotent(view_func):
    """Decorator that adds Idempotency-Key support to a DRF view method."""

    @functools.wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        key = request.META.get("HTTP_IDEMPOTENCY_KEY")
        if not key:
            return view_func(self, request, *args, **kwargs)

        if not _KEY_PATTERN.match(key):
            return Response(
                {"detail": "Invalid Idempotency-Key. Must be 1-128 alphanumeric, hyphen, or underscore characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        method = request.method
        path = request.path
        body_hash = IdempotencyRecord.hash_body(request.body)

        existing = IdempotencyRecord.objects.filter(
            key=key, user=request.user, method=method, path=path,
        ).first()

        if existing:
            if existing.expires_at < timezone.now():
                existing.delete()
            elif existing.request_body_hash != body_hash:
                return Response(
                    {"detail": "Idempotency-Key already used with a different request body."},
                    status=status.HTTP_409_CONFLICT,
                )
            else:
                response = Response(
                    existing.response_body,
                    status=existing.response_status,
                )
                response["Idempotency-Replay"] = "true"
                return response

        response = view_func(self, request, *args, **kwargs)

        if 200 <= response.status_code < 500:
            try:
                IdempotencyRecord.objects.create(
                    key=key,
                    user=request.user,
                    method=method,
                    path=path,
                    request_body_hash=body_hash,
                    response_status=response.status_code,
                    response_body=response.data,
                    expires_at=timezone.now() + timedelta(hours=IDEMPOTENCY_TTL),
                )
            except IntegrityError:
                # Concurrent request with same key won the race — replay its
                # stored response instead of returning our duplicate result.
                record = IdempotencyRecord.objects.filter(
                    key=key, user=request.user, method=method, path=path,
                ).first()
                if record:
                    response = Response(
                        record.response_body,
                        status=record.response_status,
                    )
                    response["Idempotency-Replay"] = "true"

        return response

    return wrapper
