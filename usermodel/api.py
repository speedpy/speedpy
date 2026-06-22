from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from speedpycom.api.permissions import HasScope
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from usermodel.mfa import user_has_totp, verify_totp
from usermodel.tokens import email_verified


class CurrentUserSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField(read_only=True)
    is_email_confirmed = serializers.BooleanField(read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    profile_picture_thumbnail_url = serializers.SerializerMethodField()
    date_joined = serializers.DateTimeField(read_only=True)

    @extend_schema_field(serializers.CharField(allow_null=False))
    def get_full_name(self, user) -> str:
        return user.get_full_name()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_profile_picture_url(self, user) -> str | None:
        return self._absolute_media_url(user.profile_picture)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_profile_picture_thumbnail_url(self, user) -> str | None:
        return self._absolute_media_url(user.profile_picture_thumbnail)

    def _absolute_media_url(self, image_field):
        if not image_field:
            return None
        request = self.context.get("request")
        url = image_field.url
        return request.build_absolute_uri(url) if request else url


class UpdateProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    profile_picture = serializers.ImageField(required=False, allow_null=True)

    def validate_first_name(self, value):
        from usermodel.validators import validate_no_url

        validate_no_url(value)
        return value

    def validate_last_name(self, value):
        from usermodel.validators import validate_no_url

        validate_no_url(value)
        return value

    def update(self, user, validated_data):
        for attr, value in validated_data.items():
            setattr(user, attr, value)
        user.save(update_fields=list(validated_data.keys()))
        return user


class CurrentUserAPIView(APIView):
    permission_classes = [HasScope]

    def get_required_scopes(self):
        if self.request.method == "PATCH":
            return ["write:profile"]
        return ["read:profile"]

    @property
    def required_scopes(self):
        return self.get_required_scopes()

    @extend_schema(
        tags=["user"],
        responses={
            200: CurrentUserSerializer,
            403: OpenApiResponse(description="Authentication credentials were not provided."),
        },
        operation_id="getCurrentUser",
        summary="Get the authenticated user",
    )
    def get(self, request):
        serializer = CurrentUserSerializer(
            request.user,
            context={"request": request},
        )
        return Response(serializer.data)

    @extend_schema(
        tags=["user"],
        request=UpdateProfileSerializer,
        responses={
            200: CurrentUserSerializer,
            400: OpenApiResponse(description="Validation error."),
            403: OpenApiResponse(description="Authentication credentials were not provided or CSRF check failed."),
        },
        operation_id="updateCurrentUser",
        summary="Update the authenticated user's profile",
    )
    def patch(self, request):
        serializer = UpdateProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.update(request.user, serializer.validated_data)
        return Response(
            CurrentUserSerializer(user, context={"request": request}).data
        )


class RefreshTokenSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class JWTLogoutView(APIView):
    """Blacklist a refresh token to revoke access."""

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["auth"],
        request=RefreshTokenSerializer,
        responses={
            205: OpenApiResponse(description="Token revoked."),
            400: OpenApiResponse(description="Invalid or already revoked token."),
        },
        operation_id="revokeToken",
        summary="Revoke a JWT refresh token",
    )
    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or already revoked token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class GatedTokenObtainPairSerializer(TokenObtainPairSerializer):
    mfa_code = serializers.CharField(required=False, write_only=True, help_text="TOTP code (required when MFA is enabled).")

    def validate(self, attrs):
        # Authenticate user (email + password) without minting tokens yet.
        # TokenObtainSerializer.validate authenticates and sets self.user.
        from rest_framework_simplejwt.serializers import TokenObtainSerializer

        TokenObtainSerializer.validate(self, attrs)
        user = self.user

        # Gate: verified email.
        if not email_verified(user):
            raise AuthenticationFailed("Email address is not verified.")

        # Gate: MFA (TOTP only).
        if user_has_totp(user):
            mfa_code = attrs.get("mfa_code")
            if not mfa_code:
                raise AuthenticationFailed("MFA code is required.")
            if not verify_totp(user, mfa_code):
                raise AuthenticationFailed("Invalid MFA code.")

        # All gates passed — now mint the token pair.
        refresh = self.get_token(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


@extend_schema_view(
    post=extend_schema(
        tags=["auth"],
        operation_id="createToken",
        summary="Obtain JWT access and refresh tokens",
    )
)
class TokenObtainView(TokenObtainPairView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = GatedTokenObtainPairSerializer


@extend_schema_view(
    post=extend_schema(
        tags=["auth"],
        operation_id="refreshToken",
        summary="Refresh JWT access token",
    )
)
class TokenRefreshSchemaView(TokenRefreshView):
    authentication_classes = []
    permission_classes = [AllowAny]
