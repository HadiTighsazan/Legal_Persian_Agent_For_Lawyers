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
from users.jwt_utils import get_token_hash


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


class LoginViewTests(TestCase):
    """Test cases for the login endpoint."""
    
    def setUp(self):
        """Set up test client, URLs, and test user."""
        self.client = APIClient()
        self.login_url = '/auth/login/'
        
        # Create a test user for login tests
        self.test_user = User.objects.create_user(
            email='test@example.com',
            password='SecurePass123!',
            full_name='Test User'
        )
        
    def test_login_endpoint_exists(self):
        """Test that the login endpoint exists and accepts POST requests."""
        response = self.client.post(self.login_url, {})
        # Should not return 404 (endpoint exists)
        self.assertNotEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
    def test_login_requires_post_method(self):
        """Test that login only accepts POST method."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        response = self.client.put(self.login_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        response = self.client.delete(self.login_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
    def test_login_with_valid_credentials_returns_200(self):
        """Test login with valid credentials returns 200 OK."""
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # This test should fail initially (RED phase)
        # Expected: 200 OK, but endpoint doesn't exist yet
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
    def test_login_requires_email(self):
        """Test that email is required for login."""
        data = {
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())
        
    def test_login_requires_password(self):
        """Test that password is required for login."""
        data = {
            'email': 'test@example.com'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())
        
    def test_login_with_invalid_email_returns_401(self):
        """Test login with non-existent email returns 401 Unauthorized."""
        data = {
            'email': 'nonexistent@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('error', response.json())
        
    def test_login_with_wrong_password_returns_401(self):
        """Test login with wrong password returns 401 Unauthorized."""
        data = {
            'email': 'test@example.com',
            'password': 'WrongPassword123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('error', response.json())
        
    def test_login_returns_user_data(self):
        """Test that login returns user data in response."""
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        
        # Check user data structure
        self.assertIn('user', response_data)
        user_data = response_data['user']
        
        self.assertEqual(user_data['email'], 'test@example.com')
        self.assertEqual(user_data['full_name'], 'Test User')
        self.assertIn('id', user_data)
        self.assertIn('created_at', user_data)
        self.assertIn('is_active', user_data)
        
    def test_login_returns_tokens(self):
        """Test that login returns access and refresh tokens."""
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        
        # Check tokens
        self.assertIn('accessToken', response_data)
        self.assertIn('refreshToken', response_data)
        
        access_token = response_data['accessToken']
        refresh_token = response_data['refreshToken']
        
        self.assertIsInstance(access_token, str)
        self.assertIsInstance(refresh_token, str)
        self.assertTrue(len(access_token) > 0)
        self.assertTrue(len(refresh_token) > 0)
        
    def test_login_creates_refresh_token_in_database(self):
        """Test that login creates a refresh token in database."""
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify refresh token was created
        refresh_tokens = RefreshToken.objects.filter(user=self.test_user)
        self.assertEqual(refresh_tokens.count(), 1)
        
        # Verify token is not expired
        refresh_token = refresh_tokens.first()
        self.assertGreater(refresh_token.expires_at, timezone.now())
        
    def test_login_with_inactive_user_returns_401(self):
        """Test login with inactive user returns 401 Unauthorized."""
        # Create an inactive user
        inactive_user = User.objects.create_user(
            email='inactive@example.com',
            password='SecurePass123!',
            full_name='Inactive User'
        )
        inactive_user.is_active = False
        inactive_user.save()
        
        data = {
            'email': 'inactive@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_login_tokens_are_valid_jwt(self):
        """Test that returned tokens are valid JWT tokens."""
        data = {
            'email': 'test@example.com',
            'password': 'SecurePass123!'
        }
        response = self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        
        access_token = response_data['accessToken']
        refresh_token = response_data['refreshToken']
        
        # Basic JWT format check (should have 3 parts separated by dots)
        self.assertEqual(len(access_token.split('.')), 3)
        self.assertEqual(len(refresh_token.split('.')), 3)
        
    def test_login_with_invalid_json_returns_400(self):
        """Test login with invalid JSON returns 400 Bad Request."""
        response = self.client.post(
            self.login_url,
            data='invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_login_with_empty_request_returns_400(self):
        """Test login with empty request body returns 400 Bad Request."""
        response = self.client.post(
            self.login_url,
            data=json.dumps({}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())


class RefreshTokenViewTests(TestCase):
    """Test cases for the token refresh endpoint."""
    
    def setUp(self):
        """Set up test client, URLs, and test user."""
        self.client = APIClient()
        self.refresh_url = '/auth/refresh/'
        
        # Create a test user
        self.user = User.objects.create_user(
            email='refresh@example.com',
            password='SecurePass123!',
            full_name='Refresh Test User'
        )
        
        # Create a valid refresh token for the user
        from users.jwt_utils import generate_refresh_token, get_token_hash
        from django.utils import timezone
        from datetime import timedelta
        
        self.token_id = uuid.uuid4()
        self.refresh_token = generate_refresh_token(self.user, self.token_id)
        self.token_hash = get_token_hash(self.refresh_token)
        
        # Store refresh token in database
        expires_at = timezone.now() + timedelta(days=7)
        RefreshToken.objects.create_refresh_token(
            user=self.user,
            token_hash=self.token_hash,
            expires_at=expires_at
        )
    
    def test_refresh_endpoint_exists(self):
        """Test that the refresh endpoint exists and accepts POST requests."""
        response = self.client.post(self.refresh_url, {})
        # Should not return 404 (endpoint exists)
        self.assertNotEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_refresh_requires_post_method(self):
        """Test that refresh only accepts POST method."""
        response = self.client.get(self.refresh_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        response = self.client.put(self.refresh_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        response = self.client.delete(self.refresh_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
    
    def test_refresh_with_valid_token_returns_200(self):
        """Test refresh with valid refresh token returns 200 OK with new access token."""
        data = {
            'refreshToken': self.refresh_token
        }
        
        response = self.client.post(
            self.refresh_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        response_data = response.json()
        self.assertIn('accessToken', response_data)
        
        access_token = response_data['accessToken']
        self.assertIsInstance(access_token, str)
        self.assertTrue(len(access_token) > 0)
        self.assertEqual(len(access_token.split('.')), 3)  # JWT format check
    
    def test_refresh_without_token_returns_400(self):
        """Test refresh without refresh token returns 400 Bad Request."""
        data = {}  # Missing refreshToken
        
        response = self.client.post(
            self.refresh_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token is required')
    
    def test_refresh_with_invalid_token_returns_401(self):
        """Test refresh with invalid JWT token returns 401 Unauthorized."""
        data = {
            'refreshToken': 'invalid.jwt.token.here'
        }
        
        response = self.client.post(
            self.refresh_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Invalid or expired refresh token')
    
    def test_refresh_with_expired_token_returns_401(self):
        """Test refresh with expired refresh token returns 401 Unauthorized."""
        # Create an expired refresh token
        from users.jwt_utils import generate_refresh_token, get_token_hash
        from django.utils import timezone
        from datetime import timedelta
        
        # Generate token with past expiration
        expired_token_id = uuid.uuid4()
        expired_refresh_token = generate_refresh_token(
            self.user,
            expired_token_id,
            expires_in=timedelta(seconds=-1)  # Already expired
        )
        
        # Store in database (even though expired)
        expired_token_hash = get_token_hash(expired_refresh_token)
        expired_expires_at = timezone.now() - timedelta(days=1)
        RefreshToken.objects.create_refresh_token(
            user=self.user,
            token_hash=expired_token_hash,
            expires_at=expired_expires_at
        )
        
        data = {
            'refreshToken': expired_refresh_token
        }
        
        response = self.client.post(
            self.refresh_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        response_data = response.json()
        self.assertIn('error', response_data)
        # Could be either "Invalid or expired refresh token" or "Refresh token is no longer valid"
    
    def test_refresh_with_revoked_token_returns_401(self):
        """Test refresh with revoked (deleted from DB) token returns 401."""
        # Create a token and then delete it from database (simulating revocation)
        from users.jwt_utils import generate_refresh_token, get_token_hash
        from django.utils import timezone
        from datetime import timedelta
        
        revoked_token_id = uuid.uuid4()
        revoked_refresh_token = generate_refresh_token(self.user, revoked_token_id)
        revoked_token_hash = get_token_hash(revoked_refresh_token)
        
        # Create and immediately delete (simulating logout)
        expires_at = timezone.now() + timedelta(days=7)
        refresh_token = RefreshToken.objects.create_refresh_token(
            user=self.user,
            token_hash=revoked_token_hash,
            expires_at=expires_at
        )
        refresh_token.delete()  # Revoke the token
        
        data = {
            'refreshToken': revoked_refresh_token
        }
        
        response = self.client.post(
            self.refresh_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token has been revoked')
    
    def test_refresh_with_inactive_user_returns_401(self):
        """Test refresh with inactive user account returns 401 Unauthorized."""
        # Create an inactive user
        inactive_user = User.objects.create_user(
            email='inactive@example.com',
            password='SecurePass123!',
            full_name='Inactive User'
        )
        inactive_user.is_active = False
        inactive_user.save()
        
        # Create refresh token for inactive user
        from users.jwt_utils import generate_refresh_token, get_token_hash
        from django.utils import timezone
        from datetime import timedelta
        
        inactive_token_id = uuid.uuid4()
        inactive_refresh_token = generate_refresh_token(inactive_user, inactive_token_id)
        inactive_token_hash = get_token_hash(inactive_refresh_token)
        
        expires_at = timezone.now() + timedelta(days=7)
        RefreshToken.objects.create_refresh_token(
            user=inactive_user,
            token_hash=inactive_token_hash,
            expires_at=expires_at
        )
        
        data = {
            'refreshToken': inactive_refresh_token
        }
        
        response = self.client.post(
            self.refresh_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token is no longer valid')
    
    def test_refresh_returns_different_access_token(self):
        """Test that refresh returns a new access token (different from any previous)."""
        # First, get an access token from login
        login_data = {
            'email': 'refresh@example.com',
            'password': 'SecurePass123!'
        }
        
        login_response = self.client.post(
            '/auth/login/',
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        login_access_token = login_response.json()['accessToken']
        
        # Now use refresh endpoint
        refresh_data = {
            'refreshToken': self.refresh_token
        }
        
        refresh_response = self.client.post(
            self.refresh_url,
            data=json.dumps(refresh_data),
            content_type='application/json'
        )
        
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        refresh_access_token = refresh_response.json()['accessToken']
        
        # The new access token should be different from the login access token
        self.assertNotEqual(login_access_token, refresh_access_token)
        
        # Both should be valid JWT tokens
        self.assertEqual(len(login_access_token.split('.')), 3)
        self.assertEqual(len(refresh_access_token.split('.')), 3)


class LogoutViewTests(TestCase):
    """Test cases for the logout endpoint."""
    
    def setUp(self):
        """Set up test client, URLs, and test user."""
        self.client = APIClient()
        self.logout_url = '/auth/logout/'
        
        # Create a test user
        self.user = User.objects.create_user(
            email='logout@example.com',
            password='SecurePass123!',
            full_name='Logout Test User'
        )
        
        # Generate tokens for the user
        from users.jwt_utils import generate_access_token, generate_refresh_token, get_token_hash, create_tokens_for_user
        import uuid
        from django.utils import timezone
        from datetime import timedelta
        
        self.token_id = uuid.uuid4()
        self.tokens = create_tokens_for_user(self.user, self.token_id)
        self.access_token = self.tokens['access_token']
        self.refresh_token = self.tokens['refresh_token']
        
        # Store refresh token in database
        token_hash = get_token_hash(self.refresh_token)
        expires_at = timezone.now() + timedelta(days=7)
        self.db_refresh_token = RefreshToken.objects.create_refresh_token(
            user=self.user,
            token_hash=token_hash,
            expires_at=expires_at
        )
        
        # Set authentication for the client
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
    
    def test_logout_endpoint_exists(self):
        """Test that the logout endpoint exists and accepts POST requests."""
        data = {
            'refreshToken': self.refresh_token
        }
        response = self.client.post(self.logout_url, data, format='json')
        # Should not return 404 (endpoint exists)
        self.assertNotEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_logout_requires_post_method(self):
        """Test that logout only accepts POST method."""
        # Test with GET
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        # Test with PUT
        response = self.client.put(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        # Test with DELETE
        response = self.client.delete(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
    
    def test_logout_with_valid_token_returns_204(self):
        """Test logout with valid refresh token returns 204 No Content."""
        data = {
            'refreshToken': self.refresh_token
        }
        
        response = self.client.post(self.logout_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b'')  # Empty response body
        
        # Verify token was deleted from database
        with self.assertRaises(RefreshToken.DoesNotExist):
            RefreshToken.objects.get_by_token_hash(get_token_hash(self.refresh_token))
    
    def test_logout_requires_authentication(self):
        """Test that logout endpoint requires authentication."""
        # Create a client without authentication
        unauthenticated_client = APIClient()
        
        data = {
            'refreshToken': self.refresh_token
        }
        
        response = unauthenticated_client.post(self.logout_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertIn('error', response_data)
    
    def test_logout_missing_refresh_token_returns_400(self):
        """Test logout without refresh token returns 400 Bad Request."""
        data = {}  # Missing refreshToken field
        
        response = self.client.post(self.logout_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token is required')
    
    def test_logout_with_invalid_refresh_token_returns_401(self):
        """Test logout with invalid refresh token returns 401 Unauthorized."""
        data = {
            'refreshToken': 'invalid.jwt.token.here'
        }
        
        response = self.client.post(self.logout_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token not found or already revoked')
    
    def test_logout_with_already_revoked_token_returns_401(self):
        """Test logout with already revoked token returns 401 Unauthorized."""
        # First, logout to revoke the token
        data = {
            'refreshToken': self.refresh_token
        }
        response = self.client.post(self.logout_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Try to logout again with the same token
        response = self.client.post(self.logout_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token not found or already revoked')
    
    def test_logout_with_other_users_token_returns_401(self):
        """Test logout with another user's refresh token returns 401."""
        # Create another user
        other_user = User.objects.create_user(
            email='other@example.com',
            password='SecurePass123!',
            full_name='Other User'
        )
        
        # Generate tokens for other user
        from users.jwt_utils import create_tokens_for_user, get_token_hash
        import uuid
        from django.utils import timezone
        from datetime import timedelta
        
        other_token_id = uuid.uuid4()
        other_tokens = create_tokens_for_user(other_user, other_token_id)
        other_refresh_token = other_tokens['refresh_token']
        
        # Store other user's token in database
        other_token_hash = get_token_hash(other_refresh_token)
        expires_at = timezone.now() + timedelta(days=7)
        RefreshToken.objects.create_refresh_token(
            user=other_user,
            token_hash=other_token_hash,
            expires_at=expires_at
        )
        
        # Try to logout with other user's token (authenticated as self.user)
        data = {
            'refreshToken': other_refresh_token
        }
        
        response = self.client.post(self.logout_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertIn('error', response_data)
        self.assertEqual(response_data['error'], 'Refresh token does not belong to authenticated user')
        
        # Verify other user's token still exists
        try:
            RefreshToken.objects.get_by_token_hash(other_token_hash)
        except RefreshToken.DoesNotExist:
            self.fail("Other user's token should not have been deleted")
    
    def test_logout_prevents_token_reuse(self):
        """Test that logged out refresh token cannot be used for refresh."""
        # First, logout to revoke the token
        data = {
            'refreshToken': self.refresh_token
        }
        response = self.client.post(self.logout_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Try to use the revoked token for refresh
        refresh_data = {
            'refreshToken': self.refresh_token
        }
        
        # Use a different client without authentication (refresh endpoint is public)
        refresh_client = APIClient()
        refresh_response = refresh_client.post(
            '/auth/refresh/',
            refresh_data,
            format='json'
        )
        
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)
        refresh_response_data = refresh_response.json()
        self.assertIn('error', refresh_response_data)
