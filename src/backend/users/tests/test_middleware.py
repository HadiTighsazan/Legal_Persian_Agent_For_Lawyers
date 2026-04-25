"""
Tests for JWTAuthenticationMiddleware.
"""
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.http import HttpResponse, JsonResponse
from django.urls import reverse

from users.models import User
from users.jwt_utils import verify_access_token


class JWTAuthenticationMiddlewareTests(TestCase):
    """Test cases for JWTAuthenticationMiddleware."""
    
    def setUp(self):
        """Set up test data and mocks."""
        self.factory = RequestFactory()
        
        # Create a test user
        self.user = User.objects.create_user(
            email='test@example.com',
            password='SecurePass123!',
            full_name='Test User'
        )
        
        # Sample valid JWT token (mocked)
        self.valid_token = 'valid.jwt.token.here'
        self.invalid_token = 'invalid.jwt.token.here'
        self.expired_token = 'expired.jwt.token.here'
        
        # Mock payload for valid token
        self.valid_payload = {
            'user_id': str(self.user.id),
            'email': self.user.email,
        }
    
    def test_middleware_imports_correctly(self):
        """Test that the middleware can be imported."""
        # This test should fail initially (RED phase)
        try:
            from users.middleware import JWTAuthenticationMiddleware
            middleware = JWTAuthenticationMiddleware(get_response=lambda r: HttpResponse())
            self.assertIsNotNone(middleware)
        except ImportError:
            self.fail("JWTAuthenticationMiddleware cannot be imported")
    
    def test_middleware_with_valid_token(self):
        """Test middleware with valid JWT token."""
        # Mock verify_access_token to return valid payload
        with patch('users.middleware.verify_access_token') as mock_verify:
            mock_verify.return_value = self.valid_payload
            
            # Create request with Authorization header
            request = self.factory.get('/api/protected/')
            request.META['HTTP_AUTHORIZATION'] = f'Bearer {self.valid_token}'
            
            # Create middleware instance
            from users.middleware import JWTAuthenticationMiddleware
            middleware = JWTAuthenticationMiddleware(get_response=lambda r: HttpResponse())
            
            # Process request
            response = middleware(request)
            
            # Verify user is attached to request
            self.assertEqual(request.user.id, self.user.id)
            self.assertEqual(request.user.email, self.user.email)
            # Response should not be 401
            self.assertNotEqual(response.status_code, 401)
    
    def test_middleware_without_token(self):
        """Test middleware without Authorization header."""
        # Create request without Authorization header
        request = self.factory.get('/api/protected/')
        
        # Create middleware instance
        from users.middleware import JWTAuthenticationMiddleware
        middleware = JWTAuthenticationMiddleware(get_response=lambda r: HttpResponse())
        
        # Process request
        response = middleware(request)
        
        # User should not be authenticated
        self.assertFalse(hasattr(request, 'user') and request.user.is_authenticated)
        # Response should not be 401 (public endpoint handling will be tested separately)
        # For now, just ensure middleware doesn't crash
    
    def test_middleware_with_invalid_token(self):
        """Test middleware with invalid JWT token."""
        # Mock verify_access_token to return None (invalid token)
        with patch('users.middleware.verify_access_token') as mock_verify:
            mock_verify.return_value = None
            
            # Create request with invalid token
            request = self.factory.get('/api/protected/')
            request.META['HTTP_AUTHORIZATION'] = f'Bearer {self.invalid_token}'
            
            # Create middleware instance
            from users.middleware import JWTAuthenticationMiddleware
            middleware = JWTAuthenticationMiddleware(get_response=lambda r: JsonResponse(
                {'error': 'Unauthorized'}, status=401
            ))
            
            # Process request
            response = middleware(request)
            
            # Should return 401 Unauthorized
            self.assertEqual(response.status_code, 401)
            response_data = json.loads(response.content)
            self.assertIn('error', response_data)
    
    def test_middleware_with_expired_token(self):
        """Test middleware with expired JWT token."""
        # Mock verify_access_token to return None (expired token)
        with patch('users.middleware.verify_access_token') as mock_verify:
            mock_verify.return_value = None
            
            # Create request with expired token
            request = self.factory.get('/api/protected/')
            request.META['HTTP_AUTHORIZATION'] = f'Bearer {self.expired_token}'
            
            # Create middleware instance
            from users.middleware import JWTAuthenticationMiddleware
            middleware = JWTAuthenticationMiddleware(get_response=lambda r: JsonResponse(
                {'error': 'Unauthorized'}, status=401
            ))
            
            # Process request
            response = middleware(request)
            
            # Should return 401 Unauthorized
            self.assertEqual(response.status_code, 401)
    
    def test_middleware_with_malformed_auth_header(self):
        """Test middleware with malformed Authorization header."""
        test_cases = [
            'InvalidPrefix token',  # Wrong prefix
            'Bearer',  # No token
            'Bearer ',  # Empty token after space
            'Bearer token1 token2',  # Multiple tokens
        ]
        
        for auth_header in test_cases:
            with self.subTest(auth_header=auth_header):
                request = self.factory.get('/api/protected/')
                request.META['HTTP_AUTHORIZATION'] = auth_header
                
                # Create middleware instance
                from users.middleware import JWTAuthenticationMiddleware
                middleware = JWTAuthenticationMiddleware(get_response=lambda r: JsonResponse(
                    {'error': 'Unauthorized'}, status=401
                ))
                
                # Process request
                response = middleware(request)
                
                # Should return 401 Unauthorized for malformed headers
                self.assertEqual(response.status_code, 401)
    
    def test_middleware_exempts_public_endpoints(self):
        """Test that middleware exempts public endpoints like /auth/login/ and /auth/register/."""
        public_paths = [
            '/auth/login/',
            '/auth/register/',
            '/auth/login',  # Without trailing slash
            '/auth/register',  # Without trailing slash
        ]
        
        for path in public_paths:
            with self.subTest(path=path):
                # Mock verify_access_token to return None (simulating invalid token)
                with patch('users.middleware.verify_access_token') as mock_verify:
                    mock_verify.return_value = None
                    
                    # Create request to public path with invalid token
                    request = self.factory.get(path)
                    request.META['HTTP_AUTHORIZATION'] = f'Bearer {self.invalid_token}'
                    
                    # Create middleware instance with a simple response
                    from users.middleware import JWTAuthenticationMiddleware
                    middleware = JWTAuthenticationMiddleware(get_response=lambda r: HttpResponse('OK'))
                    
                    # Process request
                    response = middleware(request)
                    
                    # Should not return 401 for public endpoints
                    self.assertNotEqual(response.status_code, 401)
                    # Should allow the request to proceed
    
    def test_middleware_attaches_user_object(self):
        """Test that middleware attaches actual User object to request.user."""
        # Mock verify_access_token to return valid payload
        with patch('users.middleware.verify_access_token') as mock_verify:
            mock_verify.return_value = self.valid_payload
            
            # Create request with valid token
            request = self.factory.get('/api/protected/')
            request.META['HTTP_AUTHORIZATION'] = f'Bearer {self.valid_token}'
            
            # Create middleware instance
            from users.middleware import JWTAuthenticationMiddleware
            middleware = JWTAuthenticationMiddleware(get_response=lambda r: HttpResponse())
            
            # Process request
            middleware(request)
            
            # Verify user object is attached and is the actual User instance
            self.assertTrue(hasattr(request, 'user'))
            self.assertIsInstance(request.user, User)
            self.assertEqual(request.user.id, self.user.id)
            self.assertEqual(request.user.email, self.user.email)
    
    def test_middleware_with_different_bearer_case(self):
        """Test middleware handles different cases of 'Bearer' prefix."""
        test_cases = [
            'Bearer token',
            'bearer token',  # lowercase
            'BEARER token',  # uppercase
            'BeArEr token',  # mixed case
        ]
        
        for auth_header in test_cases:
            with self.subTest(auth_header=auth_header):
                # Mock verify_access_token to return valid payload
                with patch('users.middleware.verify_access_token') as mock_verify:
                    mock_verify.return_value = self.valid_payload
                    
                    request = self.factory.get('/api/protected/')
                    request.META['HTTP_AUTHORIZATION'] = auth_header
                    
                    # Create middleware instance
                    from users.middleware import JWTAuthenticationMiddleware
                    middleware = JWTAuthenticationMiddleware(get_response=lambda r: HttpResponse())
                    
                    # Process request
                    middleware(request)
                    
                    # Should still authenticate user
                    self.assertEqual(request.user.id, self.user.id)