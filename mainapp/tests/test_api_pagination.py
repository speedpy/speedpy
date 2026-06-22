"""
Tests for pagination contract: page-number defaults and cursor pagination helper.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from demoapp.models import Product
from usermodel.models import User


class PageNumberPaginationTests(TestCase):
    """Default page-number pagination on list endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="pager@example.com", password="pass123"
        )
        self.client.force_authenticate(user=self.user)
        for i in range(3):
            Product.objects.create(name=f"Product {i}", sku=f"SKU-{i}", price=10 + i)

    def test_list_response_shape(self):
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)

    def test_page_size_default(self):
        """Page size defaults to 50 (all 3 products fit in one page)."""
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 3)
        self.assertIsNone(response.data["next"])


class CursorPaginationHelperTests(TestCase):
    """Verify SpeedPyCursorPagination is importable and configured."""

    def test_cursor_pagination_defaults(self):
        from speedpycom.api.pagination import SpeedPyCursorPagination

        self.assertEqual(SpeedPyCursorPagination.page_size, 50)
        self.assertEqual(SpeedPyCursorPagination.max_page_size, 200)
        self.assertEqual(SpeedPyCursorPagination.cursor_query_param, "cursor")
        self.assertEqual(SpeedPyCursorPagination.ordering, ("-created_at", "id"))
