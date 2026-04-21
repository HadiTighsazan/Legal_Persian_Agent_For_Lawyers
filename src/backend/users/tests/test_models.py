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
    
    def test_is_valid_method_exists(self):
        """Test that is_valid method exists (RED test - should fail initially)."""
        from django.utils import timezone
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=1)
        token = RefreshToken.objects.create(
            user=self.user,
            token_hash='test_hash',
            expires_at=future_time
        )
        
        # This test should fail initially if is_valid doesn't exist
        self.assertTrue(hasattr(token, 'is_valid'),
                       "RefreshToken model should have is_valid method")
    
    def test_is_valid_method_works_correctly(self):
        """Test that is_valid correctly validates tokens."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create valid token (future expiration, active user)
        future_time = timezone.now() + timedelta(days=1)
        valid_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='valid_hash',
            expires_at=future_time
        )
        
        # Create expired token
        past_time = timezone.now() - timedelta(days=1)
        expired_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='expired_hash',
            expires_at=past_time
        )
        
        # Test valid token
        self.assertTrue(valid_token.is_valid(),
                       "is_valid should return True for valid token")
        
        # Test expired token
        self.assertFalse(expired_token.is_valid(),
                        "is_valid should return False for expired token")
    
    def test_get_remaining_lifetime_method_exists(self):
        """Test that get_remaining_lifetime method exists (RED test)."""
        from django.utils import timezone
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=1)
        token = RefreshToken.objects.create(
            user=self.user,
            token_hash='test_hash',
            expires_at=future_time
        )
        
        # This test should fail initially if method doesn't exist
        self.assertTrue(hasattr(token, 'get_remaining_lifetime'),
                       "RefreshToken model should have get_remaining_lifetime method")
    
    def test_get_remaining_lifetime_works_correctly(self):
        """Test that get_remaining_lifetime returns correct timedelta."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create token with 1 day expiration
        future_time = timezone.now() + timedelta(days=1, hours=2, minutes=30)
        token = RefreshToken.objects.create(
            user=self.user,
            token_hash='test_hash',
            expires_at=future_time
        )
        
        remaining = token.get_remaining_lifetime()
        
        # Should return a timedelta
        self.assertIsInstance(remaining, timedelta,
                            "get_remaining_lifetime should return timedelta")
        
        # Should be positive (not expired)
        self.assertGreater(remaining.total_seconds(), 0,
                          "Remaining lifetime should be positive for non-expired token")
        
        # Should be approximately 1 day, 2 hours, 30 minutes
        # Allow small tolerance for test execution time
        expected_seconds = (1*24*60*60) + (2*60*60) + (30*60)  # 1 day, 2 hours, 30 minutes
        tolerance = 10  # 10 seconds tolerance
        self.assertAlmostEqual(remaining.total_seconds(), expected_seconds,
                              delta=tolerance,
                              msg="Remaining lifetime should be approximately correct")
    
    def test_revoke_method_exists(self):
        """Test that revoke method exists (RED test)."""
        from django.utils import timezone
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=1)
        token = RefreshToken.objects.create(
            user=self.user,
            token_hash='test_hash',
            expires_at=future_time
        )
        
        # This test should fail initially if method doesn't exist
        self.assertTrue(hasattr(token, 'revoke'),
                       "RefreshToken model should have revoke method")
    
    def test_revoke_method_works(self):
        """Test that revoke method deletes the token."""
        from django.utils import timezone
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=1)
        token = RefreshToken.objects.create(
            user=self.user,
            token_hash='test_hash',
            expires_at=future_time
        )
        
        token_id = token.id
        
        # Revoke should delete the token
        token.revoke()
        
        # Token should no longer exist in database
        with self.assertRaises(RefreshToken.DoesNotExist):
            RefreshToken.objects.get(id=token_id)
    
    # RefreshToken Manager Tests
    def test_refresh_token_manager_exists(self):
        """Test that RefreshToken has a custom manager."""
        self.assertTrue(hasattr(RefreshToken, 'objects'),
                       "RefreshToken should have objects manager")
        # Check if it's a custom manager (not just the default)
        manager_class = RefreshToken.objects.__class__.__name__
        self.assertNotEqual(manager_class, 'Manager',
                           "RefreshToken should have a custom manager, not default Manager")
    
    def test_create_refresh_token_manager_method_exists(self):
        """Test that create_refresh_token method exists on manager."""
        # This test should fail initially if method doesn't exist
        self.assertTrue(hasattr(RefreshToken.objects, 'create_refresh_token'),
                       "RefreshToken manager should have create_refresh_token method")
    
    def test_create_refresh_token_works_correctly(self):
        """Test that create_refresh_token creates a token correctly."""
        from django.utils import timezone
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=7)
        token_hash = 'test_token_hash_123'
        
        # Create token using manager method
        token = RefreshToken.objects.create_refresh_token(
            user=self.user,
            token_hash=token_hash,
            expires_at=future_time
        )
        
        self.assertEqual(token.user, self.user)
        self.assertEqual(token.token_hash, token_hash)
        self.assertEqual(token.expires_at, future_time)
        self.assertIsNotNone(token.created_at)
        
        # Token should be saved in database
        self.assertIsNotNone(token.id)
        db_token = RefreshToken.objects.get(id=token.id)
        self.assertEqual(db_token.token_hash, token_hash)
    
    def test_get_by_token_hash_method_exists(self):
        """Test that get_by_token_hash method exists on manager."""
        self.assertTrue(hasattr(RefreshToken.objects, 'get_by_token_hash'),
                       "RefreshToken manager should have get_by_token_hash method")
    
    def test_get_by_token_hash_works_correctly(self):
        """Test that get_by_token_hash retrieves token by hash."""
        from django.utils import timezone
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=7)
        token_hash = 'unique_token_hash_456'
        
        # Create a token
        token = RefreshToken.objects.create(
            user=self.user,
            token_hash=token_hash,
            expires_at=future_time
        )
        
        # Retrieve using manager method
        retrieved_token = RefreshToken.objects.get_by_token_hash(token_hash)
        
        self.assertEqual(retrieved_token.id, token.id)
        self.assertEqual(retrieved_token.token_hash, token_hash)
        self.assertEqual(retrieved_token.user, self.user)
    
    def test_get_valid_tokens_for_user_method_exists(self):
        """Test that get_valid_tokens_for_user method exists on manager."""
        self.assertTrue(hasattr(RefreshToken.objects, 'get_valid_tokens_for_user'),
                       "RefreshToken manager should have get_valid_tokens_for_user method")
    
    def test_get_valid_tokens_for_user_works_correctly(self):
        """Test that get_valid_tokens_for_user returns only valid tokens."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create valid token (future expiration)
        future_time = timezone.now() + timedelta(days=1)
        valid_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='valid_hash_1',
            expires_at=future_time
        )
        
        # Create expired token
        past_time = timezone.now() - timedelta(days=1)
        expired_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='expired_hash_2',
            expires_at=past_time
        )
        
        # Create another valid token for same user
        another_valid_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='valid_hash_3',
            expires_at=future_time + timedelta(days=1)
        )
        
        # Get valid tokens for user
        valid_tokens = RefreshToken.objects.get_valid_tokens_for_user(self.user)
        
        # Should return only valid tokens
        self.assertEqual(valid_tokens.count(), 2)
        self.assertIn(valid_token, valid_tokens)
        self.assertIn(another_valid_token, valid_tokens)
        self.assertNotIn(expired_token, valid_tokens)
    
    def test_cleanup_expired_tokens_method_exists(self):
        """Test that cleanup_expired_tokens method exists on manager."""
        self.assertTrue(hasattr(RefreshToken.objects, 'cleanup_expired_tokens'),
                       "RefreshToken manager should have cleanup_expired_tokens method")
    
    def test_cleanup_expired_tokens_works_correctly(self):
        """Test that cleanup_expired_tokens removes expired tokens."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create expired token
        past_time = timezone.now() - timedelta(days=1)
        expired_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='expired_hash_cleanup',
            expires_at=past_time
        )
        
        # Create valid token
        future_time = timezone.now() + timedelta(days=1)
        valid_token = RefreshToken.objects.create(
            user=self.user,
            token_hash='valid_hash_cleanup',
            expires_at=future_time
        )
        
        # Count before cleanup
        count_before = RefreshToken.objects.count()
        
        # Run cleanup
        deleted_count = RefreshToken.objects.cleanup_expired_tokens()
        
        # Count after cleanup
        count_after = RefreshToken.objects.count()
        
        # Should delete only expired token
        self.assertEqual(deleted_count, 1)
        self.assertEqual(count_before - count_after, 1)
        
        # Expired token should be gone
        with self.assertRaises(RefreshToken.DoesNotExist):
            RefreshToken.objects.get(id=expired_token.id)
        
        # Valid token should still exist
        self.assertTrue(RefreshToken.objects.filter(id=valid_token.id).exists())
    
    def test_revoke_all_for_user_method_exists(self):
        """Test that revoke_all_for_user method exists on manager."""
        self.assertTrue(hasattr(RefreshToken.objects, 'revoke_all_for_user'),
                       "RefreshToken manager should have revoke_all_for_user method")
    
    def test_revoke_all_for_user_works_correctly(self):
        """Test that revoke_all_for_user removes all tokens for a user."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create another user
        other_user = User.objects.create_user(
            email='other@example.com',
            password='password123'
        )
        
        future_time = timezone.now() + timedelta(days=1)
        
        # Create tokens for main user
        token1 = RefreshToken.objects.create(
            user=self.user,
            token_hash='hash1',
            expires_at=future_time
        )
        token2 = RefreshToken.objects.create(
            user=self.user,
            token_hash='hash2',
            expires_at=future_time
        )
        
        # Create token for other user (should not be affected)
        other_token = RefreshToken.objects.create(
            user=other_user,
            token_hash='other_hash',
            expires_at=future_time
        )
        
        # Count before revocation
        count_before = RefreshToken.objects.count()
        user_count_before = RefreshToken.objects.filter(user=self.user).count()
        
        # Revoke all tokens for main user
        revoked_count = RefreshToken.objects.revoke_all_for_user(self.user)
        
        # Count after revocation
        count_after = RefreshToken.objects.count()
        user_count_after = RefreshToken.objects.filter(user=self.user).count()
        
        # Should revoke only tokens for specified user
        self.assertEqual(revoked_count, 2)
        self.assertEqual(user_count_before - user_count_after, 2)
        self.assertEqual(count_before - count_after, 2)
        
        # Main user's tokens should be gone
        self.assertFalse(RefreshToken.objects.filter(user=self.user).exists())
        
        # Other user's token should still exist
        self.assertTrue(RefreshToken.objects.filter(id=other_token.id).exists())
    
    def test_is_token_valid_method_exists(self):
        """Test that is_token_valid method exists on manager."""
        self.assertTrue(hasattr(RefreshToken.objects, 'is_token_valid'),
                       "RefreshToken manager should have is_token_valid method")
    
    def test_is_token_valid_works_correctly(self):
        """Test that is_token_valid checks token validity by hash."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create valid token
        future_time = timezone.now() + timedelta(days=1)
        valid_hash = 'valid_token_hash_check'
        valid_token = RefreshToken.objects.create(
            user=self.user,
            token_hash=valid_hash,
            expires_at=future_time
        )
        
        # Create expired token
        past_time = timezone.now() - timedelta(days=1)
        expired_hash = 'expired_token_hash_check'
        expired_token = RefreshToken.objects.create(
            user=self.user,
            token_hash=expired_hash,
            expires_at=past_time
        )
        
        # Test valid token
        self.assertTrue(RefreshToken.objects.is_token_valid(valid_hash),
                       "is_token_valid should return True for valid token")
        
        # Test expired token
        self.assertFalse(RefreshToken.objects.is_token_valid(expired_hash),
                        "is_token_valid should return False for expired token")
        
        # Test non-existent token
        self.assertFalse(RefreshToken.objects.is_token_valid('non_existent_hash'),
                        "is_token_valid should return False for non-existent token")
