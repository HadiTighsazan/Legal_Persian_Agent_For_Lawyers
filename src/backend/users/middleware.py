"""
DEPRECATED: JWT Authentication Middleware for DocuChat.

This middleware is deprecated. JWT authentication is now handled by
DRF's `rest_framework_simplejwt.authentication.JWTAuthentication` configured
in `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']` in settings.py.

This file is kept for reference only and is no longer included in MIDDLEWARE.
"""
import warnings
import re
from typing import Callable, Optional

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.deprecation import MiddlewareMixin

from users.jwt_utils import verify_access_token
from users.models import User

warnings.warn(
    "JWTAuthenticationMiddleware is deprecated. "
    "Use DRF's JWTAuthentication via DEFAULT_AUTHENTICATION_CLASSES instead.",
    DeprecationWarning,
    stacklevel=2,
)


class JWTAuthenticationMiddleware(MiddlewareMixin):
    """
    DEPRECATED: Middleware for JWT authentication.
    
    This middleware is deprecated. JWT authentication is now handled by
    DRF's `rest_framework_simplejwt.authentication.JWTAuthentication`.
    
    Extracts Bearer token from Authorization header, validates it,
    and attaches the authenticated user to request.user.
    
    Public endpoints (login, register) are exempt from authentication.
    """
    
    # Public endpoints that don't require authentication
    PUBLIC_ENDPOINTS = [
        # Authentication endpoints
        '/auth/login/',
        '/auth/register/',
        '/auth/refresh/',
        '/auth/login',
        '/auth/register',
        '/auth/refresh',
        
        # Health check endpoints (for Docker, Kubernetes, load balancers)
        '/health/',
        '/health/ready/',
        '/health/live/',
        '/health',
        '/health/ready',
        '/health/live',
        
        # API documentation endpoints
        '/swagger/',
        '/redoc/',
        '/swagger',
        '/redoc',
    ]
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware."""
        self.get_response = get_response
    
    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request.
        
        Args:
            request: The HTTP request
            
        Returns:
            HTTP response
        """
        # Check if this is a public endpoint
        if self._is_public_endpoint(request.path):
            # Public endpoint, skip authentication
            return self.get_response(request)
        
        # Extract and validate token
        token = self._extract_token(request)
        
        if token is None:
            # No token provided
            return self._unauthorized_response("No authentication token provided")
        
        # Verify the token
        payload = verify_access_token(token)
        
        if payload is None:
            # Invalid or expired token
            return self._unauthorized_response("Invalid or expired authentication token")
        
        # Get user from payload
        user = self._get_user_from_payload(payload)
        
        if user is None:
            # User not found
            return self._unauthorized_response("User not found")
        
        # Attach user to request
        request.user = user
        
        # Continue processing the request
        return self.get_response(request)
    
    def _is_public_endpoint(self, path: str) -> bool:
        """
        Check if the given path is a public endpoint.
        
        Args:
            path: Request path
            
        Returns:
            bool: True if public endpoint, False otherwise
        """
        # Remove query string if present
        path_without_query = path.split('?')[0]
        
        # Normalize path (ensure consistent comparison)
        normalized_path = path_without_query.rstrip('/')
        
        for public_path in self.PUBLIC_ENDPOINTS:
            if normalized_path == public_path.rstrip('/'):
                return True
        
        return False
    
    def _extract_token(self, request: HttpRequest) -> Optional[str]:
        """
        Extract Bearer token from Authorization header.
        
        Args:
            request: HTTP request
            
        Returns:
            str: Token if found, None otherwise
        """
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if not auth_header:
            return None
        
        # Split by space and check for Bearer prefix (case-insensitive)
        parts = auth_header.split()
        
        if len(parts) != 2:
            return None
        
        prefix, token = parts
        
        # Check if prefix is Bearer (case-insensitive)
        if prefix.lower() != 'bearer':
            return None
        
        return token.strip()
    
    def _get_user_from_payload(self, payload: dict) -> Optional[User]:
        """
        Get User object from JWT payload.
        
        Args:
            payload: Decoded JWT payload
            
        Returns:
            User: User object if found, None otherwise
        """
        try:
            user_id = payload.get('user_id')
            if not user_id:
                return None
            
            # Get user by ID
            return User.objects.get(id=user_id)
        except (User.DoesNotExist, ValueError):
            return None
    
    def _unauthorized_response(self, message: str = "Unauthorized") -> JsonResponse:
        """
        Create a 401 Unauthorized response.
        
        Args:
            message: Error message
            
        Returns:
            JsonResponse: 401 response with error message
        """
        return JsonResponse(
            {'error': message},
            status=401
        )