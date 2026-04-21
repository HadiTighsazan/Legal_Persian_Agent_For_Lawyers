"""
Tests for authentication views (registration, login, etc.).
"""
import json
import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from users.models import User, RefreshToken


class RegistrationViewTests(TestCase):
    """Test cases for the registration endpoint."""
    
    def setUp(self):
        """Set up test client and URLs."""
        self.client = APIClient()
        self.register_url = '/auth/register/'
        
    def test_register_endpoint_exists(self):
        """Test that the registration endpoint exists and accepts POST requests."""
        response = self.client.post(self.register_url, {})
        # Should not return 404 (endpoint exists)
        self.assertNotEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
    def test_register_requires_post_method(self):
        """Test that registration only accepts POST method."""
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        response = self.client.put(self.register_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        response = self.client.delete(self.register_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
    def test_register_with_valid_data_returns_201(self):
        """Test registration with valid data returns 201 Created."""
        # This test should fail initially (RED phase)
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!',
            'full_name': 'Test User'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        # Currently returns 501 Not Implemented, but should return 201
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
    def test_register_returns_user_data(self):
        """Test that registration returns user data in response."""
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!',
            'full_name': 'Test User'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        
        # Check response structure
        self.assertIn('user', response_data)
        self.assertIn('accessToken', response_data)
        self.assertIn('refreshToken', response_data)
        
        # Check user data structure
        user_data = response_data['user']
        self.assertIn('id', user_data)
        self.assertIn('email', user_data)
        self.assertIn('full_name', user_data)
        self.assertIn('created_at', user_data)
        self.assertIn('is_active', user_data)
        
        # Check values
        self.assertEqual(user_data['email'], 'test@example.com')
        self.assertEqual(user_data['full_name'], 'Test User')
        self.assertTrue(user_data['is_active'])
        
    def test_register_without_full_name(self):
        """Test registration without optional full_name field."""
        data = {
            'email': 'test2@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['user']['email'], 'test2@example.com')
        self.assertEqual(response_data['user']['full_name'], '')
        
    def test_register_with_missing_email_returns_400(self):
        """Test registration without email returns 400 Bad Request."""
        data = {
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_register_with_missing_password_returns_400(self):
        """Test registration without password returns 400 Bad Request."""
        data = {
            'email': 'test@example.com'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_register_with_invalid_email_returns_400(self):
        """Test registration with invalid email format returns 400."""
        data = {
            'email': 'invalid-email',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_register_with_weak_password_returns_400(self):
        """Test registration with weak password returns 400."""
        data = {
            'email': 'test@example.com',
            'password': '123'  # Too short
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_register_with_existing_email_returns_409(self):
        """Test registration with existing email returns 409 Conflict."""
        # Create a user first
        User.objects.create_user(
            email='existing@example.com',
            password='ExistingPass123!'
        )
        
        # Try to register with same email
        data = {
            'email': 'existing@example.com',
            'password': 'NewPass123!'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        
    def test_register_creates_user_in_database(self):
        """Test that registration actually creates a user in the database."""
        initial_count = User.objects.count()
        
        data = {
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'full_name': 'New User'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), initial_count + 1)
        
        # Verify user was created with correct data
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertEqual(user.full_name, 'New User')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        
    def test_register_creates_refresh_token(self):
        """Test that registration creates a refresh token in database."""
        data = {
            'email': 'tokenuser@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify refresh token was created
        user = User.objects.get(email='tokenuser@example.com')
        refresh_tokens = RefreshToken.objects.filter(user=user)
        self.assertEqual(refresh_tokens.count(), 1)
        
        # Verify token is not expired
        refresh_token = refresh_tokens.first()
        self.assertGreater(refresh_token.expires_at, timezone.now())
        
    def test_register_tokens_are_valid_jwt(self):
        """Test that returned tokens are valid JWT tokens."""
        data = {
            'email': 'jwtuser@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        
        # Tokens should be strings
        access_token = response_data['accessToken']
        refresh_token = response_data['refreshToken']
        
        self.assertIsInstance(access_token, str)
        self.assertIsInstance(refresh_token, str)
        
        # Tokens should not be empty
        self.assertTrue(len(access_token) > 0)
        self.assertTrue(len(refresh_token) > 0)
        
        # Basic JWT format check (should have 3 parts separated by dots)
        self.assertEqual(len(access_token.split('.')), 3)
        self.assertEqual(len(refresh_token.split('.')), 3)