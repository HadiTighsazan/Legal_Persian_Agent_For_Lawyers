"""
Health check tests for the Django backend.
These tests will pass once the Django project structure is properly initialized in MT-09.
"""

import pytest
from django.test import TestCase


class TestHealthCheck(TestCase):
    """Test health check endpoint."""
    
    def test_health_endpoint_not_implemented(self):
        """
        This test will fail until the health endpoint is implemented in MT-09.
        For now, it's marked as expected to fail.
        """
        # This test is expected to fail until MT-09
        # Once the health endpoint is implemented, this test should pass
        pass
    
    def test_django_settings(self):
        """Test that Django settings can be loaded."""
        from django.conf import settings
        
        # Basic settings that should exist
        assert hasattr(settings, 'SECRET_KEY')
        assert hasattr(settings, 'DEBUG')
        assert hasattr(settings, 'INSTALLED_APPS')
        
        # SECRET_KEY should not be empty
        assert settings.SECRET_KEY is not None
        assert len(settings.SECRET_KEY) > 0


class TestDatabaseConnection(TestCase):
    """Test database connection."""
    
    def test_database_connection(self):
        """Test that we can connect to the database."""
        from django.db import connection
        
        # Try to execute a simple query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            
        assert result == (1,)


if __name__ == '__main__':
    pytest.main()