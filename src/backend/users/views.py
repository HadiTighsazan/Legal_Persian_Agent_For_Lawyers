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
