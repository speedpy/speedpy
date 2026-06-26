"""
SPEEDPY_DEMO: Read-only Product API — canonical example for business resource endpoints.

Copy this pattern when adding list/detail endpoints for new models.
Remove this file before production (see demo-content.json and PRODUCTION_READY.md).
"""

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
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
        description=(
            "Return a paginated list of all products. "
            "Requires the `read:products` scope."
        ),
        responses={
            200: ProductSerializer(many=True),
            403: OpenApiResponse(description="Authentication credentials were not provided."),
        },
        examples=[
            OpenApiExample(
                "Product list",
                value={
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": "b2c3d4e5-f6a7-8901-bcde-f23456789abc",
                            "name": "Wireless Headphones",
                            "sku": "WH-1000",
                            "category": "hardware",
                            "status": "active",
                            "price": "79.99",
                            "inventory": 150,
                            "description": "Bluetooth over-ear headphones with noise cancellation.",
                            "created_at": "2025-04-01T08:00:00Z",
                            "updated_at": "2025-06-10T12:30:00Z",
                        }
                    ],
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
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
        description=(
            "Return a single product by its primary key. "
            "Requires the `read:products` scope."
        ),
        responses={
            200: ProductSerializer,
            403: OpenApiResponse(description="Authentication credentials were not provided."),
            404: OpenApiResponse(description="Product not found."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
