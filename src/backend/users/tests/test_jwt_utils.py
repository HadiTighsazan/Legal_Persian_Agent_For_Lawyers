"""
Tests for JWT utilities module.
"""
import uuid
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.conf import settings
from users.models import User, RefreshToken


class JWTUtilsTest(TestCase):
    """Test cases for JWT utilities module."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpassword123'
        )
        self.token_id = uuid.uuid4()
    
    # Test 1: Module import test (will fail initially)
    def test_jwt_utils_module_exists(self):
        """Test that jwt_utils module can be imported."""
        try:
            from users import jwt_utils
            self.assertTrue(True, "jwt_utils module exists")
        except ImportError:
            self.fail("jwt_utils module does not exist")
    
    # Test 2: Function existence tests
    def test_generate_access_token_function_exists(self):
        """Test that generate_access_token function exists."""
        try:
            from users.jwt_utils import generate_access_token
            self.assertTrue(callable(generate_access_token), 
                          "generate_access_token should be callable")
        except ImportError:
            self.fail("generate_access_token function does not exist")
    
    def test_generate_refresh_token_function_exists(self):
        """Test that generate_refresh_token function exists."""
        try:
            from users.jwt_utils import generate_refresh_token
            self.assertTrue(callable(generate_refresh_token), 
                          "generate_refresh_token should be callable")
        except ImportError:
            self.fail("generate_refresh_token function does not exist")
    
    def test_verify_access_token_function_exists(self):
        """Test that verify_access_token function exists."""
        try:
            from users.jwt_utils import verify_access_token
            self.assertTrue(callable(verify_access_token), 
                          "verify_access_token should be callable")
        except ImportError:
            self.fail("verify_access_token function does not exist")
    
    def test_verify_refresh_token_function_exists(self):
        """Test that verify_refresh_token function exists."""
        try:
            from users.jwt_utils import verify_refresh_token
            self.assertTrue(callable(verify_refresh_token), 
                          "verify_refresh_token should be callable")
        except ImportError:
            self.fail("verify_refresh_token function does not exist")
    
    # Test 3: Functionality tests (will fail initially)
    def test_generate_access_token_creates_valid_token(self):
        """Test that generate_access_token creates a valid JWT token."""
        from users.jwt_utils import generate_access_token, verify_access_token
        
        # Generate token
        token = generate_access_token(self.user)
        
        # Verify token is not None
        self.assertIsNotNone(token, "Token should not be None")
        self.assertIsInstance(token, str, "Token should be a string")
        
        # Verify token can be decoded
        payload = verify_access_token(token)
        self.assertIsNotNone(payload, "Payload should not be None")
        
        # Check payload structure
        self.assertIn('userId', payload, "Payload should contain userId")
        self.assertIn('email', payload, "Payload should contain email")
        self.assertIn('type', payload, "Payload should contain type")
        
        # Check payload values
        self.assertEqual(str(payload['userId']), str(self.user.id), 
                        "userId should match user id")
        self.assertEqual(payload['email'], self.user.email, 
                        "email should match user email")
        self.assertEqual(payload['type'], 'access', 
                        "type should be 'access'")
    
    def test_generate_refresh_token_creates_valid_token(self):
        """Test that generate_refresh_token creates a valid JWT token."""
        from users.jwt_utils import generate_refresh_token, verify_refresh_token
        
        # Generate token
        token = generate_refresh_token(self.user, self.token_id)
        
        # Verify token is not None
        self.assertIsNotNone(token, "Token should not be None")
        self.assertIsInstance(token, str, "Token should be a string")
        
        # Verify token can be decoded
        payload = verify_refresh_token(token)
        self.assertIsNotNone(payload, "Payload should not be None")
        
        # Check payload structure
        self.assertIn('userId', payload, "Payload should contain userId")
        self.assertIn('tokenId', payload, "Payload should contain tokenId")
        self.assertIn('type', payload, "Payload should contain type")
        
        # Check payload values
        self.assertEqual(str(payload['userId']), str(self.user.id), 
                        "userId should match user id")
        self.assertEqual(str(payload['tokenId']), str(self.token_id), 
                        "tokenId should match provided token id")
        self.assertEqual(payload['type'], 'refresh', 
                        "type should be 'refresh'")
    
    def test_access_token_expiration(self):
        """Test that access token expires after specified time."""
        from users.jwt_utils import generate_access_token, verify_access_token
        
        # Generate token with very short expiration (1 second)
        token = generate_access_token(self.user, expires_in=timedelta(seconds=1))
        
        # Token should be valid initially
        payload = verify_access_token(token)
        self.assertIsNotNone(payload, "Token should be valid initially")
        
        # Note: We can't easily test expiration without mocking time
        # This test will be expanded with proper mocking
    
    def test_refresh_token_expiration(self):
        """Test that refresh token expires after specified time."""
        from users.jwt_utils import generate_refresh_token, verify_refresh_token
        
        # Generate token with very short expiration (1 second)
        token = generate_refresh_token(self.user, self.token_id, 
                                      expires_in=timedelta(seconds=1))
        
        # Token should be valid initially
        payload = verify_refresh_token(token)
        self.assertIsNotNone(payload, "Token should be valid initially")
        
        # Note: We can't easily test expiration without mocking time
        # This test will be expanded with proper mocking
    
    def test_invalid_token_verification(self):
        """Test that invalid tokens are rejected."""
        from users.jwt_utils import verify_access_token, verify_refresh_token
        
        # Test with malformed token
        invalid_token = "invalid.token.here"
        
        # Both verification functions should return None for invalid tokens
        access_result = verify_access_token(invalid_token)
        refresh_result = verify_refresh_token(invalid_token)
        
        self.assertIsNone(access_result, 
                         "verify_access_token should return None for invalid token")
        self.assertIsNone(refresh_result, 
                         "verify_refresh_token should return None for invalid token")
    
    def test_expired_token_verification(self):
        """Test that expired tokens are rejected."""
        from users.jwt_utils import generate_access_token, verify_access_token
        
        # Generate token with past expiration
        # This will require mocking time or using negative timedelta
        # For now, we'll test the function signature
        
        # Note: This test will be expanded with proper mocking
    
    def test_token_payload_structure(self):
        """Test that token payloads have correct structure."""
        from users.jwt_utils import generate_access_token, generate_refresh_token
        from users.jwt_utils import verify_access_token, verify_refresh_token
        
        # Generate both types of tokens
        access_token = generate_access_token(self.user)
        refresh_token = generate_refresh_token(self.user, self.token_id)
        
        # Verify and check payloads
        access_payload = verify_access_token(access_token)
        refresh_payload = verify_refresh_token(refresh_token)
        
        # Access token payload checks
        self.assertEqual(access_payload['type'], 'access', 
                        "Access token type should be 'access'")
        self.assertIn('userId', access_payload, 
                     "Access token should have userId")
        self.assertIn('email', access_payload, 
                     "Access token should have email")
        self.assertNotIn('tokenId', access_payload, 
                        "Access token should not have tokenId")
        
        # Refresh token payload checks
        self.assertEqual(refresh_payload['type'], 'refresh', 
                        "Refresh token type should be 'refresh'")
        self.assertIn('userId', refresh_payload, 
                     "Refresh token should have userId")
        self.assertIn('tokenId', refresh_payload, 
                     "Refresh token should have tokenId")
        self.assertIn('email', refresh_payload, 
                     "Refresh token should have email")
    
    def test_default_expiration_times(self):
        """Test that default expiration times are used when not specified."""
        from users.jwt_utils import generate_access_token, generate_refresh_token
        from users.jwt_utils import verify_access_token, verify_refresh_token
        
        # Generate tokens without specifying expiration
        access_token = generate_access_token(self.user)
        refresh_token = generate_refresh_token(self.user, self.token_id)
        
        # Both tokens should be valid
        access_payload = verify_access_token(access_token)
        refresh_payload = verify_refresh_token(refresh_token)
        
        self.assertIsNotNone(access_payload, 
                            "Access token with default expiration should be valid")
        self.assertIsNotNone(refresh_payload, 
                            "Refresh token with default expiration should be valid")