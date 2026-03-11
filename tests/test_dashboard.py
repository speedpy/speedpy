"""
Tests for authenticated views: dashboard and user profile.
Unauthenticated requests are expected to redirect (302) to login.
"""
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_dashboard(auth_client):
    response = auth_client.get(reverse("dashboard"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_profile_requires_login(client):
    response = client.get(reverse("account_profile"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_profile(auth_client):
    response = auth_client.get(reverse("account_profile"))
    assert response.status_code == 200
