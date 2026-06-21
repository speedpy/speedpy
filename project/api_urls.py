from django.urls import path
from drf_spectacular.utils import extend_schema

from mainapp.api.products import ProductDetailAPIView, ProductListAPIView
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
]
