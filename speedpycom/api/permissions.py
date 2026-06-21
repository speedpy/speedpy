"""
Scope-based permission stubs for the SpeedPy API.

Scope taxonomy (Phase 2):
    read:profile   — GET /api/v1/me/
    write:profile  — PATCH /api/v1/me/
    read:teams     — Team list, detail, members (read)
    write:teams    — Invitations and other team writes
    admin          — Reserved for future elevated operations

These stubs pass through for session-authenticated users (Phase 1–2).
Once token/OAuth auth lands (Phases 3–6), HasScope will enforce scope
checks against the token's granted scopes.

Custom scopes follow the pattern: read:<domain>, write:<domain>
(e.g. read:products, write:products).
"""

from rest_framework.permissions import IsAuthenticated


class HasScope(IsAuthenticated):
    """
    Permission class that will enforce scope-based access control
    once token authentication is implemented.

    Usage::

        class MyAPIView(APIView):
            permission_classes = [HasScope]
            required_scopes = ["read:products"]

    For session auth (current), this behaves identically to
    IsAuthenticated. When token auth lands, it will additionally
    verify that the token includes the required scopes.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        # Phase 1–2: session auth has implicit full access.
        # Future phases will check request.auth scopes against
        # view.required_scopes here.
        return True
