"""
Tests for User model and related authentication models.
"""
import uuid
from django.test import TestCase
from django.contrib.auth.hashers import make_password, check_password
from users.models import User, APIKey, RefreshToken


class UserModelTest(TestCase):
    """Test cases for the User model."""
    
    def test_create_user(self):
        """Test creating a regular user."""
        user = User.objects.create_user(
            email='test@example.com',
            password='testpassword123'
        )
        
        self.assertEqual(user.email, 'test@example.com')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
        
    def test_create_superuser(self):
        """Test creating a superuser."""
        superuser = User.objects.create_superuser(
            email='admin@example.com',
            password='adminpassword123'
        )
        
        self.assertEqual(superuser.email, 'admin@example.com')
        self.assertTrue(superuser.is_active)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        
    def test_email_uniqueness(self):
        """Test that email must be unique."""
        User.objects.create_user(
            email='duplicate@example.com',
            password='password123'
        )
        
        with self.assertRaises(Exception):
            User.objects.create_user(
                email='duplicate@example.com',
                password='anotherpassword'
            )
            
    def test_password_hashing(self):
        """Test that passwords are hashed and not stored in plain text."""
        user = User.objects.create_user(
            email='hash_test@example.com',
            password='plaintextpassword'
        )
        
        # Password should not be stored in plain text
        self.assertNotEqual(user.password_hash, 'plaintextpassword')
        # Password hash should be a valid Django hash
        self.assertTrue(user.password_hash.startswith('pbkdf2_sha256$'))
        
    def test_verify_password_method_exists(self):
        """Test that verify_password method exists (RED test - should fail initially)."""
        user = User.objects.create_user(
            email='verify_test@example.com',
            password='testpassword'
        )
        
        # This test should fail initially if verify_password doesn't exist
        self.assertTrue(hasattr(user, 'verify_password'),
                       "User model should have verify_password method")
        
    def test_verify_password_works_correctly(self):
        """Test that verify_password correctly verifies passwords."""
        user = User.objects.create_user(
            email='verify_test2@example.com',
            password='correctpassword'
        )
        
        # Test with correct password
        self.assertTrue(user.verify_password('correctpassword'),
                       "verify_password should return True for correct password")
        
        # Test with incorrect password
        self.assertFalse(user.verify_password('wrongpassword'),
                        "verify_password should return False for incorrect password")
        
    def test_get_full_name(self):
        """Test get_full_name method."""
        user_with_name = User.objects.create_user(
            email='named@example.com',
            password='password123',
            full_name='John Doe'
        )
        
        user_without_name = User.objects.create_user(
            email='nonamed@example.com',
            password='password123'
        )
        
        self.assertEqual(user_with_name.get_full_name(), 'John Doe')
        self.assertEqual(user_without_name.get_full_name(), 'nonamed@example.com')
        
    def test_get_short_name(self):
        """Test get_short_name method."""
        user = User.objects.create_user(
            email='short@example.com',
            password='password123'
        )
        
        self.assertEqual(user.get_short_name(), 'short@example.com')


class APIKeyModelTest(TestCase):
    """Test cases for the APIKey model."""
    
    def test_create_api_key(self):
        """Test creating an API key."""
        user = User.objects.create_user(
            email='apikey_user@example.com',
            password='password123'
        )
        
        api_key = APIKey.objects.create(
            user=user,
            key_hash='hashed_key_value',
            name='Test API Key'
        )
        
        self.assertEqual(api_key.user, user)
        self.assertEqual(api_key.key_hash, 'hashed_key_value')
        self.assertEqual(api_key.name, 'Test API Key')
        self.assertTrue(api_key.is_active)
        self.assertIsNotNone(api_key.created_at)


class RefreshTokenModelTest(TestCase):
    """Test cases for the RefreshToken model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='token_user@example.com',
            password='password123'
        )
    
    def test_create_refresh_token(self):
        """Test creating a refresh token."""
        from django.utils import timezone
        from datetime import datetime, timezone as dt_timezone
        
        # Create a timezone-aware datetime object for testing (UTC)
        expected_expires_at = datetime(2024, 12, 31, 23, 59, 59, tzinfo=dt_timezone.utc)
        
        refresh_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='hashed_token_value',
            expires_at=expected_expires_at
        )
        
        self.assertEqual(refresh_token.user, self.user)
        self.assertEqual(refresh_token.token_hash, 'hashed_token_value')
        # Compare datetime objects directly instead of string representations
        self.assertEqual(refresh_token.expires_at, expected_expires_at)
        self.assertIsNotNone(refresh_token.created_at)
        
    def test_is_expired_method(self):
        """Test the is_expired method."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create token that expired in the past
        past_time = timezone.now() - timedelta(days=1)
        expired_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='expired_hash',
            expires_at=past_time
        )
        
        # Create token that expires in the future
        future_time = timezone.now() + timedelta(days=1)
        valid_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='valid_hash',
            expires_at=future_time
        )
        
        self.assertTrue(expired_token.is_expired())
        self.assertFalse(valid_token.is_expired())
