"""API middleware for request correlation IDs."""

import re
import uuid

import structlog


_VALID_REQUEST_ID = re.compile(r"^[\w\-]{1,128}$")


class RequestIDMiddleware:
    """
    Ensure every API response carries an ``X-Request-ID`` header.

    - If the client sends a valid ``X-Request-ID``, it is accepted and echoed.
    - If the header is missing, django_structlog's ``RequestMiddleware``
      generates one automatically (it runs earlier in the stack).
    - If the client sends an invalid ID (wrong length or characters), it is
      silently replaced with a generated UUID to avoid breaking clients.

    This middleware reads the ``request_id`` that django_structlog already
    bound into contextvars, so it always matches what appears in logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Validate inbound header — replace bad values before the request
        # proceeds further.  django_structlog has already read the header in
        # its prepare() method, so we also rebind the contextvars if we
        # replaced the value.
        raw = request.META.get("HTTP_X_REQUEST_ID", "")
        if raw and not _VALID_REQUEST_ID.match(raw):
            new_id = str(uuid.uuid4())
            request.META["HTTP_X_REQUEST_ID"] = new_id
            structlog.contextvars.bind_contextvars(request_id=new_id)

        response = self.get_response(request)

        # Read the authoritative request_id from structlog context (set by
        # django_structlog or our override above).
        ctx = structlog.contextvars.get_contextvars()
        request_id = ctx.get("request_id")
        if request_id:
            response["X-Request-ID"] = request_id

        return response
