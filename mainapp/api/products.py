"""
Read-only Product API — canonical example for business resource endpoints.

Copy this pattern when adding list/detail endpoints for new models.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.generics import ListAPIView, RetrieveAPIView

from demoapp.models import Product
from speedpycom.api.permissions import HasScope


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "sku",
            "category",
            "status",
            "price",
            "inventory",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProductListAPIView(ListAPIView):
    """List all products with pagination."""

    serializer_class = ProductSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:products"]

    def get_queryset(self):
        return Product.objects.all()

    @extend_schema(
        tags=["products"],
        operation_id="listProducts",
        summary="List products",
        responses={
            200: ProductSerializer(many=True),
            403: OpenApiResponse(description="Authentication credentials were not provided."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ProductDetailAPIView(RetrieveAPIView):
    """Retrieve a single product by ID."""

    serializer_class = ProductSerializer
    permission_classes = [HasScope]
    required_scopes = ["read:products"]

    def get_queryset(self):
        return Product.objects.all()

    @extend_schema(
        tags=["products"],
        operation_id="getProduct",
        summary="Get a product",
        responses={
            200: ProductSerializer,
            403: OpenApiResponse(description="Authentication credentials were not provided."),
            404: OpenApiResponse(description="Product not found."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
