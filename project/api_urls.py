from django.urls import path

from mainapp.api.products import ProductDetailAPIView, ProductListAPIView
from mainapp.api.teams import (
    TeamDetailAPIView,
    TeamInvitationCreateAPIView,
    TeamListAPIView,
    TeamMembersAPIView,
)
from usermodel.api import (
    CurrentUserAPIView,
    JWTLogoutView,
    TokenObtainView,
    TokenRefreshSchemaView,
)

app_name = "api"

urlpatterns = [
    path("auth/token/", TokenObtainView.as_view(), name="token_obtain"),
    path("auth/token/refresh/", TokenRefreshSchemaView.as_view(), name="token_refresh"),
    path("auth/token/revoke/", JWTLogoutView.as_view(), name="token_revoke"),
    path("v1/me/", CurrentUserAPIView.as_view(), name="current_user"),
    path("v1/products/", ProductListAPIView.as_view(), name="product_list"),
    path("v1/products/<uuid:pk>/", ProductDetailAPIView.as_view(), name="product_detail"),
    path("v1/teams/", TeamListAPIView.as_view(), name="team_list"),
    path("v1/teams/<uuid:team_id>/", TeamDetailAPIView.as_view(), name="team_detail"),
    path("v1/teams/<uuid:team_id>/members/", TeamMembersAPIView.as_view(), name="team_members"),
    path("v1/teams/<uuid:team_id>/invitations/", TeamInvitationCreateAPIView.as_view(), name="team_invitation_create"),
]
