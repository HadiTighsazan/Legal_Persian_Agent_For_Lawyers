"""
Root conftest for pytest-django configuration.

Provides:
- Django settings module declaration (fallback)
- Shared fixtures for all test modules
"""
from __future__ import annotations

import os

# Ensure Django settings are configured before any test imports
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
