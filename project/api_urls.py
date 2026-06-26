from django.urls import path

from mainapp.api.jobs import DemoJobCreateView, JobStatusView
from mainapp.api.products import ProductDetailAPIView, ProductListAPIView
from mainapp.api.teams import (
    TeamDetailAPIView,
    TeamInvitationCreateAPIView,
    TeamListAPIView,
    TeamMembersAPIView,
)
from mainapp.api.webhooks import (
    TeamWebhookDeliveryDetailView,
    TeamWebhookDeliveryListView,
    TeamWebhookDeliveryRetryView,
    TeamWebhookEndpointDetailView,
    TeamWebhookEndpointListCreateView,
    TeamWebhookEndpointRotateSecretView,
    TeamWebhookEndpointTestView,
    UserWebhookEndpointListView,
)
from speedpycom.api.health import HealthCheckView
from speedpycom.api.manifest import IntegrationManifestView
from usermodel.api import (
    CurrentUserAPIView,
    JWTLogoutView,
    TokenObtainView,
    TokenRefreshSchemaView,
)

app_name = "api"

urlpatterns = [
    path("v1/health/", HealthCheckView.as_view(), name="health_check"),
    path("v1/health/manifest/", IntegrationManifestView.as_view(), name="integration_manifest"),
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
    # Jobs
    path("v1/jobs/demo/", DemoJobCreateView.as_view(), name="demo_job_create"),
    path("v1/jobs/<uuid:job_id>/", JobStatusView.as_view(), name="job_status"),
    # Webhooks — user-scoped
    path("v1/webhooks/", UserWebhookEndpointListView.as_view(), name="webhook_list_user"),
    # Webhooks — team-scoped
    path("v1/teams/<uuid:team_id>/webhooks/", TeamWebhookEndpointListCreateView.as_view(), name="webhook_list"),
    path("v1/teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/", TeamWebhookEndpointDetailView.as_view(), name="webhook_detail"),
    path("v1/teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/rotate-secret/", TeamWebhookEndpointRotateSecretView.as_view(), name="webhook_rotate_secret"),
    path("v1/teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/test/", TeamWebhookEndpointTestView.as_view(), name="webhook_test"),
    path("v1/teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/deliveries/", TeamWebhookDeliveryListView.as_view(), name="webhook_delivery_list"),
    path("v1/teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/deliveries/<int:delivery_id>/", TeamWebhookDeliveryDetailView.as_view(), name="webhook_delivery_detail"),
    path("v1/teams/<uuid:team_id>/webhooks/<uuid:webhook_id>/deliveries/<int:delivery_id>/retry/", TeamWebhookDeliveryRetryView.as_view(), name="webhook_delivery_retry"),
]
