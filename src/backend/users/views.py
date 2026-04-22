"""
Authentication views for the DocuChat system.

This module contains API endpoints for user authentication including
registration, login, token refresh, and logout.
"""
import uuid
from datetime import timedelta
from typing import Dict, Any

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from users.models import User, RefreshToken
from users.jwt_utils import (
    generate_access_token,
    generate_refresh_token,
    verify_access_token,
    verify_refresh_token,
    create_tokens_for_user,
    get_token_hash,
)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request: Request) -> Response:
    """
    Register a new user.
    
    Endpoint: POST /auth/register
    
    Request body:
    {
        "email": "user@example.com",
        "password": "securepassword123",
        "full_name": "John Doe"  # optional
    }
    
    Response (201 Created):
    {
        "user": {
            "id": "uuid",
            "email": "user@example.com",
            "full_name": "John Doe",
            "created_at": "2024-01-01T00:00:00Z",
            "is_active": true
        },
        "accessToken": "jwt_token_here",
        "refreshToken": "jwt_refresh_token_here"
    }
    
    Error responses:
    - 400 Bad Request: Invalid input (missing fields, invalid email, weak password)
    - 409 Conflict: Email already exists
    """
    try:
        data = request.data
        
        # Validate required fields
        email = data.get('email')
        password = data.get('password')
        
        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if not password:
            return Response(
                {"error": "Password is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate email format
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Invalid email format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate password strength (min 8 chars)
        if len(password) < 8:
            return Response(
                {"error": "Password must be at least 8 characters long"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "Email already exists"},
                status=status.HTTP_409_CONFLICT
            )
        
        # Create user
        full_name = data.get('full_name', '')
        user = User.objects.create_user(
            email=email,
            password=password,
            full_name=full_name
        )
        
        # Generate token ID for refresh token
        token_id = uuid.uuid4()
        
        # Generate tokens
        tokens = create_tokens_for_user(user, token_id)
        
        # Store refresh token hash in database
        token_hash = get_token_hash(tokens['refresh_token'])
        expires_at = timezone.now() + timedelta(days=7)  # 7 days expiry
        
        RefreshToken.objects.create_refresh_token(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at
        )
        
        # Prepare response
        user_data = {
            'id': str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'is_active': user.is_active
        }
        
        return Response(
            {
                'user': user_data,
                'accessToken': tokens['access_token'],
                'refreshToken': tokens['refresh_token']
            },
            status=status.HTTP_201_CREATED
        )
        
    except Exception as e:
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Registration error: {str(e)}")
        
        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request: Request) -> Response:
    """
    Authenticate a user and return JWT tokens.
    
    Endpoint: POST /auth/login
    
    Request body:
    {
        "email": "user@example.com",
        "password": "securepassword123"
    }
    
    Response (200 OK):
    {
        "user": {
            "id": "uuid",
            "email": "user@example.com",
            "full_name": "John Doe",
            "created_at": "2024-01-01T00:00:00Z",
            "is_active": true
        },
        "accessToken": "jwt_token_here",
        "refreshToken": "jwt_refresh_token_here"
    }
    
    Error responses:
    - 400 Bad Request: Invalid input (missing fields, invalid email, invalid JSON)
    - 401 Unauthorized: Invalid credentials (wrong email or password)
    - 401 Unauthorized: User account is inactive
    """
    try:
        # Handle JSON parsing errors
        try:
            data = request.data
        except Exception as json_error:
            return Response(
                {"error": "Invalid JSON format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate required fields
        email = data.get('email')
        password = data.get('password')
        
        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if not password:
            return Response(
                {"error": "Password is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate email format
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Invalid email format"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Find user by email
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Check if user is active
        if not user.is_active:
            return Response(
                {"error": "Account is inactive"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Verify password
        if not user.verify_password(password):
            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Generate token ID for refresh token
        token_id = uuid.uuid4()
        
        # Generate tokens
        tokens = create_tokens_for_user(user, token_id)
        
        # Store refresh token hash in database
        token_hash = get_token_hash(tokens['refresh_token'])
        expires_at = timezone.now() + timedelta(days=7)  # 7 days expiry
        
        RefreshToken.objects.create_refresh_token(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at
        )
        
        # Prepare response
        user_data = {
            'id': str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'is_active': user.is_active
        }
        
        return Response(
            {
                'user': user_data,
                'accessToken': tokens['access_token'],
                'refreshToken': tokens['refresh_token']
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Login error: {str(e)}")
        
        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_view(request: Request) -> Response:
    """
    Refresh an access token using a refresh token.
    
    Endpoint: POST /auth/refresh
    
    Request body:
    {
        "refreshToken": "jwt_refresh_token_here"
    }
    
    Response (200 OK):
    {
        "accessToken": "new_jwt_access_token_here"
    }
    
    Error responses:
    - 400 Bad Request: Missing refresh token
    - 401 Unauthorized: Invalid, expired, or revoked refresh token
    """
    try:
        data = request.data
        
        # Validate required field
        refresh_token = data.get('refreshToken')
        
        if not refresh_token:
            return Response(
                {"error": "Refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify refresh token JWT
        payload = verify_refresh_token(refresh_token)
        
        if not payload:
            return Response(
                {"error": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Extract user ID and token ID from payload
        user_id = payload.get('userId')
        token_id = payload.get('tokenId')
        
        if not user_id or not token_id:
            return Response(
                {"error": "Invalid token payload"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get token hash for database lookup
        token_hash = get_token_hash(refresh_token)
        
        try:
            # Find the refresh token in database
            db_refresh_token = RefreshToken.objects.get_by_token_hash(token_hash)
            
            # Check if token is valid (not expired, user active)
            if not db_refresh_token.is_valid():
                return Response(
                    {"error": "Refresh token is no longer valid"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Get the user
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {"error": "User not found"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if user is active
            if not user.is_active:
                return Response(
                    {"error": "User account is inactive"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Generate new access token (same user, same token_id for refresh token)
            # Note: We're not rotating the refresh token, just generating new access token
            access_token = generate_access_token(user)
            
            return Response(
                {
                    'accessToken': access_token
                },
                status=status.HTTP_200_OK
            )
            
        except RefreshToken.DoesNotExist:
            # Token hash not found in database (possibly revoked)
            return Response(
                {"error": "Refresh token has been revoked"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
    except Exception as e:
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Token refresh error: {str(e)}")
        
        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
