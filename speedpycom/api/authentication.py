import structlog
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = structlog.get_logger(__name__)


class PersonalAccessTokenAuthentication(BaseAuthentication):
    """
    Bearer token authentication using PersonalAccessToken.

    Expects: Authorization: Bearer spd_<hex>
    """

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(f"{self.keyword} "):
            return None

        raw_token = auth_header[len(self.keyword) + 1 :]
        if not raw_token:
            return None

        from usermodel.models import TOKEN_PREFIX

        # Only handle tokens with the PAT prefix; let JWTs pass through.
        if not raw_token.startswith(TOKEN_PREFIX):
            return None

        from usermodel.models import PersonalAccessToken

        pat = PersonalAccessToken.authenticate(raw_token)
        if pat is None:
            logger.warning("pat_auth_failed", token_prefix=raw_token[:8])
            raise AuthenticationFailed("Invalid or expired token.")

        if not pat.user.is_active:
            logger.warning("pat_auth_inactive_user", user_id=str(pat.user.id))
            raise AuthenticationFailed("User account is disabled.")

        pat.record_usage()
        logger.info(
            "pat_auth_success",
            user_id=str(pat.user.id),
            token_name=pat.name,
            token_id=str(pat.id),
        )
        return (pat.user, pat)

    def authenticate_header(self, request):
        return self.keyword
