from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from mainapp import views
import speedpycom.views
from oauth2_provider.urls import (
    base_urlpatterns as oauth2_base_urlpatterns,
    management_urlpatterns as oauth2_management_urlpatterns,
    oidc_urlpatterns as oauth2_oidc_urlpatterns,
)
from speedpycom.api.dcr import DynamicClientRegistrationView
from speedpycom.api.health import RootHealthCheckView
from speedpycom.api.manifest import WellKnownManifestView
from usermodel.views import (
    PersonalAccessTokenCreateView,
    PersonalAccessTokenListView,
    PersonalAccessTokenRevokeView,
    ProfileEditView,
)


def api_docs_view(view_class, **kwargs):
    base_view = view_class.as_view(**kwargs)
    staff_view = staff_member_required(base_view)

    def wrapper(request, *args, **kw):
        if settings.API_DOCS_PUBLIC:
            return base_view(request, *args, **kw)
        return staff_view(request, *args, **kw)

    return wrapper


urlpatterns = [
    path("", views.WelcomeToSpeedPyView.as_view(), name="welcome"),
    path("demo/", include("demoapp.urls")),  # SPEEDPY_DEMO: demo Product CRUD — remove before production
    path("pricing", views.PricingView.as_view(), name="pricing"),
    path("contact/", views.ContactView.as_view(), name="contact"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("speedpyui-preview/", views.SpeedpyuiPreviewView.as_view(), name="speedpyui_preview"),
    path(
        "speedpyui-preview/FormView",
        views.SpeedpyuiFormViewExampleView.as_view(),
        name="speedpyui_preview_form_view",
    ),
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/profile/", ProfileEditView.as_view(), name="account_profile"),
    path("accounts/tokens/", PersonalAccessTokenListView.as_view(), name="account_pat_list"),
    path("accounts/tokens/create/", PersonalAccessTokenCreateView.as_view(), name="account_pat_create"),
    path("accounts/tokens/<uuid:pk>/revoke/", PersonalAccessTokenRevokeView.as_view(), name="account_pat_revoke"),
    # SES delivery events. Opt-in because it is Amazon-specific — drop this
    # line if your ESP is not SES. See docs/email-bounces.md.
    path("", include("speedpycom.urls_email_events")),
    path("og-image.png", speedpycom.views.default_og_image, name="default-og-image"),
    path("o/register/", DynamicClientRegistrationView.as_view(), name="dcr-register"),
    # Mount django-oauth-toolkit route by route, not wholesale. DOT 3.4's
    # aggregate ``oauth2_provider.urls`` also carries ``metadata_urlpatterns``
    # (RFC 8414 + RFC 9728) and ``dcr_urlpatterns`` (its own DCR). Both stay off
    # by default. The metadata documents belong on their own hosts (RFC 8414 on
    # the app/issuer host, RFC 9728 on the MCP host) and are mounted there with
    # the MCP transport when MCP_ENABLED — not wholesale under ``/o/`` — so we do
    # not open them prematurely here. DCR stays shut: the project's own gated
    # ``/o/register/`` above is the single registration door, and mounting DOT's
    # DCR would only shadow it while exposing its RFC 7592 management route. See
    # agents_docs/working_with_hosted_mcp.md.
    path(
        "o/",
        include(
            (
                oauth2_base_urlpatterns
                + oauth2_management_urlpatterns
                + oauth2_oidc_urlpatterns,
                "oauth2_provider",
            ),
            namespace="oauth2_provider",
        ),
    ),
    path("__debug__/", include("debug_toolbar.urls")),
    path("health/", RootHealthCheckView.as_view(), name="root_health_check"),
    path(".well-known/speedpy.json", WellKnownManifestView.as_view(), name="well_known_manifest"),
    path("api/schema/", api_docs_view(SpectacularAPIView), name="api_schema"),
    path(
        "api/docs/",
        api_docs_view(SpectacularSwaggerView, url_name="api_schema"),
        name="api_docs",
    ),
    path(
        "api/redoc/",
        api_docs_view(SpectacularRedocView, url_name="api_schema"),
        name="api_redoc",
    ),
    path("api/", include("project.api_urls")),
    path("", include("mainapp.urls")),
]

# The hosted MCP plane. Mounted only when MCP is enabled. Host separation (which
# routes answer on the mcp. host vs the app host) is enforced by
# speedpycom.api.mcp_host.MCPHostMiddleware and the metadata view's own host check.
if settings.MCP_ENABLED:
    from django.utils.module_loading import import_string
    from oauth2_provider.views import OAuthServerMetadataView
    from speedpycom.api.mcp_metadata import mcp_metadata_urlpatterns
    from speedpycom.api.oauth_consent import ConsentAuthorizationView

    endpoint_view = import_string(settings.MCP_ENDPOINT_VIEW).as_view()
    metadata_view = import_string(settings.MCP_METADATA_VIEW).as_view()

    # The hardened consent screen shadows DOT's /o/authorize/ (inserted ahead of
    # the "o/" include). CIMD is on with MCP and is safe only with this view.
    urlpatterns.insert(
        0,
        path("o/authorize/", ConsentAuthorizationView.as_view(), name="mcp_authorize"),
    )
    urlpatterns += [
        # RFC 8414 authorization-server metadata — the app/issuer host root.
        path(
            ".well-known/oauth-authorization-server",
            OAuthServerMetadataView.as_view(),
            name="oauth-server-metadata",
        ),
        # RFC 9728 protected-resource metadata — the MCP host (the view 404s
        # elsewhere). Single-tenant shapes; a connector adds its scoped patterns.
        *mcp_metadata_urlpatterns(metadata_view),
        # The transport — the MCP host. A tenancy-aware connector adds its scoped
        # routes (e.g. mcp/t/<slug>) pointing at the same view.
        path("mcp", endpoint_view, name="mcp_endpoint"),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
