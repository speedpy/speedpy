"""
Scope-based permission for the SpeedPy API.

Scope taxonomy:
    read:profile   — GET /api/v1/me/
    write:profile  — PATCH /api/v1/me/
    read:teams     — Team list, detail, members (read)
    write:teams    — Invitations and other team writes
    admin          — Reserved for future elevated operations

Session-authenticated users have implicit full access (no scope restriction).
PAT and OAuth2 tokens are checked against the token's granted scopes.

New tokens require at least one explicit scope. Legacy tokens with empty
scopes are still granted full access for backward compatibility.

Custom scopes follow the pattern: read:<domain>, write:<domain>
(e.g. read:products, write:products). Register them in
``settings.OAUTH2_PROVIDER["SCOPES"]``.
"""

from rest_framework.permissions import IsAuthenticated


class HasScope(IsAuthenticated):
    """
    Permission class that enforces scope-based access control.

    Usage::

        class MyAPIView(APIView):
            permission_classes = [HasScope]
            required_scopes = ["read:products"]

    - Session auth / JWT: implicit full access (no scope check).
    - PAT with empty scopes: full access (legacy tokens only).
    - PAT with scopes: allowed only if token scopes include all required.
    - OAuth2 token: allowed only if token scopes include all required.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        required = set(getattr(view, "required_scopes", []))
        if not required:
            return True

        # Check PAT scopes
        from usermodel.models import PersonalAccessToken

        if isinstance(request.auth, PersonalAccessToken):
            if not request.auth.scopes:
                return True
            return required.issubset(set(request.auth.scopes))

        # Check OAuth2 token scopes
        try:
            from oauth2_provider.models import AccessToken as OAuth2AccessToken

            if isinstance(request.auth, OAuth2AccessToken):
                granted = set(request.auth.scope.split())
                return required.issubset(granted)
        except ImportError:
            pass

        # Session auth / JWT — full access
        return True
