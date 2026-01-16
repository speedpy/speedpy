from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from mainapp import views
import speedpycom.views
from usermodel.views import ProfileEditView
urlpatterns = [
    path("", views.WelcomeToSpeedPyView.as_view(), name="welcome"),
    path("pricing", views.PricingView.as_view(), name="pricing"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/profile/", ProfileEditView.as_view(), name="account_profile"),
    path("og-image.png", speedpycom.views.default_og_image, name="default-og-image"),
    path("__debug__/", include("debug_toolbar.urls")),
    path("", include("mainapp.urls")),
]
