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
    path("og-image.png", speedpycom.views.default_og_image, name="default-og-image"),
    path("o/register/", DynamicClientRegistrationView.as_view(), name="dcr-register"),
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
