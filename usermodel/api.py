from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


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


class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["user"],
        responses={200: CurrentUserSerializer},
        operation_id="getCurrentUser",
        summary="Get the authenticated user",
    )
    def get(self, request):
        serializer = CurrentUserSerializer(
            request.user,
            context={"request": request},
        )
        return Response(serializer.data)
