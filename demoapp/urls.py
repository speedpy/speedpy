from django.urls import path

from demoapp import views


urlpatterns = [
    path("products/", views.ProductListView.as_view(), name="demo_product_list"),
    path("products/populate-demo/", views.ProductPopulateDemoView.as_view(), name="demo_product_populate"),
    path("products/new/", views.ProductCreateView.as_view(), name="demo_product_create"),
    path("products/<uuid:pk>/edit/", views.ProductUpdateView.as_view(), name="demo_product_update"),
    path("products/<uuid:pk>/", views.ProductDetailView.as_view(), name="demo_product_detail"),
    path("products/<uuid:pk>/delete/", views.ProductDeleteView.as_view(), name="demo_product_delete"),
]
