from drf_spectacular.extensions import OpenApiAuthenticationExtension


class PersonalAccessTokenScheme(OpenApiAuthenticationExtension):
    target_class = "speedpycom.api.authentication.PersonalAccessTokenAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": "Personal access token. Create at /accounts/tokens/.",
        }


class JWTScheme(OpenApiAuthenticationExtension):
    target_class = "rest_framework_simplejwt.authentication.JWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT access token from /api/auth/token/.",
        }
