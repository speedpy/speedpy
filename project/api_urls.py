from django.urls import path

from mainapp.api.products import ProductDetailAPIView, ProductListAPIView
from usermodel.api import CurrentUserAPIView

app_name = "api"

urlpatterns = [
    path("v1/me/", CurrentUserAPIView.as_view(), name="current_user"),
    path("v1/products/", ProductListAPIView.as_view(), name="product_list"),
    path("v1/products/<uuid:pk>/", ProductDetailAPIView.as_view(), name="product_detail"),
]
