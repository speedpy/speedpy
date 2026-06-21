"""
Scope-based permission for the SpeedPy API.

Scope taxonomy:
    read:profile   — GET /api/v1/me/
    write:profile  — PATCH /api/v1/me/
    read:teams     — Team list, detail, members (read)
    write:teams    — Invitations and other team writes
    admin          — Reserved for future elevated operations

Session-authenticated users have implicit full access (no scope restriction).
PAT-authenticated requests are checked against the token's granted scopes.
An empty scopes list on a PAT means full access (no restriction).

Custom scopes follow the pattern: read:<domain>, write:<domain>
(e.g. read:products, write:products).
"""

from rest_framework.permissions import IsAuthenticated


class HasScope(IsAuthenticated):
    """
    Permission class that enforces scope-based access control for PATs.

    Usage::

        class MyAPIView(APIView):
            permission_classes = [HasScope]
            required_scopes = ["read:products"]

    - Session auth: implicit full access (no scope check).
    - PAT with empty scopes: full access.
    - PAT with scopes: request is allowed only if the token's scopes
      include all of the view's required_scopes.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        from usermodel.models import PersonalAccessToken

        if not isinstance(request.auth, PersonalAccessToken):
            # Session auth — full access.
            return True

        pat = request.auth
        if not pat.scopes:
            # Empty scopes list means full access.
            return True

        required = set(getattr(view, "required_scopes", []))
        if not required:
            # View doesn't declare required scopes — allow.
            return True

        granted = set(pat.scopes)
        return required.issubset(granted)
