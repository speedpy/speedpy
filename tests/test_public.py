"""
Tests for public views that require no authentication.
"""
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_welcome_page(client):
    response = client.get(reverse("welcome"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_pricing_page(client):
    response = client.get(reverse("pricing"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_og_image(client):
    response = client.get(reverse("default-og-image"))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
