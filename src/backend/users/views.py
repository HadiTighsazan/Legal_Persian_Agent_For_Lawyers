"""
Authentication views for the DocuChat system.

This module contains API endpoints for user authentication including
registration, login, token refresh, and logout.
"""
import logging
import uuid
from typing import Dict, Any

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
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
from users.serializers import (
    LoginSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


@api_view(['POST'])
@authentication_classes([])
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
        # Validate input using RegisterSerializer
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            # Check for email conflict specifically
            if 'email' in errors and any(
                'already exists' in str(err).lower()
                for err in errors['email']
            ):
                return Response(
                    {"error": "Email already exists"},
                    status=status.HTTP_409_CONFLICT,
                )
            # Return first error for other validation failures
            first_field = list(errors.keys())[0]
            first_error = errors[first_field][0]
            return Response(
                {"error": str(first_error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated_data = serializer.validated_data
        email = validated_data['email']
        password = validated_data['password']
        full_name = validated_data.get('full_name') or ''

        # Create user
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
        refresh_lifetime = settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']
        expires_at = timezone.now() + refresh_lifetime

        RefreshToken.objects.create_refresh_token(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at
        )

        # Prepare response using UserSerializer
        user_data = UserSerializer(user).data

        return Response(
            {
                'user': user_data,
                'accessToken': tokens['access_token'],
                'refreshToken': tokens['refresh_token']
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.exception("Registration error")

        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([])
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
        except Exception:
            return Response(
                {"error": "Invalid JSON format"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate input using LoginSerializer
        serializer = LoginSerializer(data=data)
        if not serializer.is_valid():
            first_field = list(serializer.errors.keys())[0]
            first_error = serializer.errors[first_field][0]
            return Response(
                {"error": str(first_error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated_data = serializer.validated_data
        email = validated_data['email']
        password = validated_data['password']

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
        refresh_lifetime = settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']
        expires_at = timezone.now() + refresh_lifetime

        RefreshToken.objects.create_refresh_token(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at
        )

        # Prepare response using UserSerializer
        user_data = UserSerializer(user).data

        return Response(
            {
                'user': user_data,
                'accessToken': tokens['access_token'],
                'refreshToken': tokens['refresh_token']
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.exception("Login error")

        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile_view(request: Request) -> Response:
    """
    Get or update current user profile.
    
    Endpoint: GET /users/me
    Endpoint: PATCH /users/me
    
    GET Response (200 OK):
    {
        "id": "uuid",
        "email": "user@example.com",
        "full_name": "John Doe",
        "is_active": true,
        "created_at": "2026-04-18T10:00:00Z",
        "updated_at": "2026-04-18T10:00:00Z"
    }
    
    PATCH Request Body (partial update):
    {
        "full_name": "Updated Name",  # optional
        "email": "newemail@example.com"  # optional
    }
    
    PATCH Response (200 OK):
    {
        "id": "uuid",
        "email": "newemail@example.com",
        "full_name": "Updated Name",
        "is_active": true,
        "created_at": "2026-04-18T10:00:00Z",
        "updated_at": "2026-04-18T10:01:00Z"
    }
    
    Error responses:
    - 401 Unauthorized: No valid authentication token
    - 400 Bad Request: Invalid email format, invalid JSON
    - 409 Conflict: Email already exists
    """
    user = request.user
    
    if request.method == 'GET':
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)

    elif request.method == 'PATCH':
        # Validate request data using DRF serializer
        serializer = ProfileUpdateSerializer(
            data=request.data,
            context={'user': user},
            partial=True,
        )

        if not serializer.is_valid():
            # Extract the first error message
            errors = serializer.errors
            first_field = list(errors.keys())[0]
            first_error = errors[first_field][0]

            # Determine appropriate HTTP status code
            error_msg = str(first_error)
            if 'already exists' in error_msg.lower():
                return Response(
                    {'error': error_msg},
                    status=status.HTTP_409_CONFLICT,
                )
            else:
                return Response(
                    {'error': error_msg},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Apply validated updates
        validated_data = serializer.validated_data

        if 'full_name' in validated_data:
            user.full_name = validated_data['full_name']

        if 'email' in validated_data:
            user.email = validated_data['email']

        user.save()

        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([])
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
        user_id = payload.get('user_id')
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
            
            # Rotate refresh token: revoke old one and issue a new one
            # Revoke the old refresh token from database
            db_refresh_token.revoke()
            
            # Generate new token ID and new refresh token
            new_token_id = uuid.uuid4()
            new_refresh_token = generate_refresh_token(user, new_token_id)
            
            # Store new refresh token hash in database
            new_token_hash = get_token_hash(new_refresh_token)
            refresh_lifetime = settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']
            new_expires_at = timezone.now() + refresh_lifetime
            
            RefreshToken.objects.create_refresh_token(
                user=user,
                token_hash=new_token_hash,
                expires_at=new_expires_at
            )
            
            # Generate new access token
            access_token = generate_access_token(user)
            
            return Response(
                {
                    'accessToken': access_token,
                    'refreshToken': new_refresh_token
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
        logger.exception("Token refresh error")

        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    """
    Logout and revoke a refresh token.
    
    Endpoint: POST /auth/logout
    
    Request body:
    {
        "refreshToken": "jwt_refresh_token_here"
    }
    
    Response: 204 No Content (empty body)
    
    Error responses:
    - 400 Bad Request: Missing refresh token
    - 401 Unauthorized: Refresh token not found or already revoked
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
        
        # Get token hash for database lookup
        token_hash = get_token_hash(refresh_token)
        
        try:
            # Find the refresh token in database
            db_refresh_token = RefreshToken.objects.get_by_token_hash(token_hash)
            
            # Verify the token belongs to the authenticated user
            if db_refresh_token.user.id != request.user.id:
                return Response(
                    {"error": "Refresh token does not belong to authenticated user"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Revoke (delete) the refresh token
            db_refresh_token.revoke()
            
            # Return 204 No Content
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        except RefreshToken.DoesNotExist:
            # Token hash not found in database (already revoked or invalid)
            return Response(
                {"error": "Refresh token not found or already revoked"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
    except Exception as e:
        logger.exception("Logout error")

        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
