from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from mainapp import views

urlpatterns = [
    path("", views.WelcomeToSpeedPyView.as_view(), name="welcome"),
    path("pricing", views.PricingView.as_view(), name="pricing"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("__debug__/", include("debug_toolbar.urls")),
    path("", include("mainapp.urls")),
]
