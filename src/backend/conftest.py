"""
Root conftest for pytest-django configuration.

Provides:
- Django settings module declaration (fallback)
- Shared fixtures for all test modules
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import pytest


@pytest.fixture
def api_client():
    """Return an unauthenticated API client."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user(db):
    """Create and return a test user."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass123",
        full_name="Test User",
    )


@pytest.fixture
def auth_headers(user) -> dict[str, str]:
    """Return Authorization headers for the test user."""
    from users.jwt_utils import create_tokens_for_user

    tokens = create_tokens_for_user(user)
    return {
        "HTTP_AUTHORIZATION": f"Bearer {tokens['accessToken']}",
    }


@pytest.fixture
def authenticated_client(api_client, auth_headers):
    """Return an authenticated API client."""
    from rest_framework.test import APIClient

    api_client.credentials(**auth_headers)
    return api_client
