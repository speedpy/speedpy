"""
Pagination helpers for SpeedPy API endpoints.

SpeedPy uses page-number pagination by default (``PageNumberPagination``
with ``PAGE_SIZE = 50``).  For high-volume or frequently-changing list
endpoints, cursor pagination avoids the issues of unstable offsets.

Usage::

    from speedpycom.api.pagination import SpeedPyCursorPagination

    class MyHighVolumeListView(ListAPIView):
        pagination_class = SpeedPyCursorPagination
        ordering = ["-created_at", "id"]   # must be deterministic
        ...
"""

from rest_framework.pagination import CursorPagination


class SpeedPyCursorPagination(CursorPagination):
    """
    Cursor-based pagination for high-volume list endpoints.

    Requires that the view's default ordering uses a unique, monotonic column
    (or a combination that is deterministic).  ``-created_at, id`` is a good
    default for models that inherit from ``BaseModel``.
    """

    page_size = 50
    ordering = ("-created_at", "id")
    cursor_query_param = "cursor"
    page_size_query_param = "page_size"
    max_page_size = 200
