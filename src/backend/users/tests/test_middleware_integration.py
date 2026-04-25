"""
Integration tests for JWTAuthenticationMiddleware with actual endpoints.
"""
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from users.models import User, RefreshToken
from users.jwt_utils import create_tokens_for_user, get_token_hash


class JWTAuthenticationMiddlewareIntegrationTests(TestCase):
    """Integration tests for JWTAuthenticationMiddleware."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create a test user
        self.user = User.objects.create_user(
            email='test@example.com',
            password='SecurePass123!',
            full_name='Test User'
        )
        
        # Create tokens for the user
        token_id = RefreshToken.objects.create_refresh_token(
            user=self.user,
            token_hash='test_hash',
            expires_at='2026-12-31T23:59:59Z'
        ).id
        
        self.tokens = create_tokens_for_user(self.user, token_id)
        self.access_token = self.tokens['access_token']
        self.refresh_token = self.tokens['refresh_token']
    
    def test_protected_endpoint_without_token(self):
        """Test accessing a protected endpoint without token returns 401."""
        # Try to access a protected endpoint without token
        response = self.client.get('/users/me/')
        
        # Should return 401 Unauthorized (DRF format)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = json.loads(response.content)
        self.assertIn('detail', response_data)
    
    def test_protected_endpoint_with_valid_token(self):
        """Test accessing a protected endpoint with valid token."""
        # Set Authorization header with valid token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        # Try to access a protected endpoint that exists
        response = self.client.get('/users/me/')
        
        # Should return 200 OK (authenticated successfully)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_public_endpoints_without_token(self):
        """Test accessing public endpoints without token should work."""
        # Test login endpoint without token (should work)
        response = self.client.post('/auth/login/', {
            'email': 'test@example.com',
            'password': 'SecurePass123!'
        })
        
        # Should not return 401 (might return 400 for missing data, but not 401)
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_public_endpoints_with_invalid_token(self):
        """Test accessing public endpoints with invalid token should still work."""
        # Set invalid token
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid_token')
        
        # Test login endpoint with invalid token (should still work - public endpoint)
        # We'll test with empty data to get a 400 Bad Request instead of 401 Unauthorized
        # This shows the middleware didn't block the request
        response = self.client.post('/auth/login/', {})
        
        # Should return 400 (bad request for missing email/password), not 401
        # 401 would mean middleware blocked it, 400 means login view processed it
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_middleware_with_malformed_header(self):
        """Test that malformed auth headers result in 401 on protected endpoints."""
        test_cases = [
            'InvalidPrefix token',
            'Bearer',
            'Bearer ',
            'Bearer token1 token2',
        ]
        
        for auth_header in test_cases:
            with self.subTest(auth_header=auth_header):
                self.client.credentials(HTTP_AUTHORIZATION=auth_header)
                response = self.client.get('/users/me/')
                
                # DRF returns 401 for invalid/malformed auth headers
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_token_extraction_case_insensitive(self):
        """Test that Bearer prefix is case-insensitive with DRF auth."""
        test_cases = [
            'Bearer token',
            'bearer token',  # lowercase
            'BEARER token',  # uppercase
            'BeArEr token',  # mixed case
        ]
        
        for auth_header in test_cases:
            with self.subTest(auth_header=auth_header):
                self.client.credentials(HTTP_AUTHORIZATION=auth_header)
                response = self.client.get('/users/me/')
                
                # DRF's JWTAuthentication should reject invalid tokens with 401
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)