"""
JWT Utilities for authentication.

This module provides functions for generating and verifying JWT tokens
for the DocuChat authentication system.
"""
import uuid
from datetime import timedelta
from typing import Optional, Dict, Any

from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from users.models import User


def generate_access_token(user: User, expires_in: Optional[timedelta] = None) -> str:
    """
    Generate a JWT access token for a user.
    
    Args:
        user: The user to generate token for
        expires_in: Optional custom expiration time. If not provided,
                   uses default from settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']
    
    Returns:
        str: JWT access token string
    
    Raises:
        ValueError: If user is None or invalid
    """
    if not user or not isinstance(user, User):
        raise ValueError("Valid user object is required")
    
    # Create access token
    access_token = AccessToken()
    
    # Set custom claims
    access_token['user_id'] = str(user.id)
    access_token['email'] = user.email
    
    # Set expiration
    if expires_in:
        access_token.set_exp(lifetime=expires_in)
    
    # Return token string
    return str(access_token)


def generate_refresh_token(user: User, token_id: uuid.UUID, 
                          expires_in: Optional[timedelta] = None) -> str:
    """
    Generate a JWT refresh token for a user.
    
    Args:
        user: The user to generate token for
        token_id: Unique identifier for the refresh token (stored in database)
        expires_in: Optional custom expiration time. If not provided,
                   uses default from settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']
    
    Returns:
        str: JWT refresh token string
    
    Raises:
        ValueError: If user or token_id is None or invalid
    """
    if not user or not isinstance(user, User):
        raise ValueError("Valid user object is required")
    
    if not token_id or not isinstance(token_id, uuid.UUID):
        raise ValueError("Valid token_id (UUID) is required")
    
    # Create refresh token
    refresh_token = RefreshToken()
    
    # Set custom claims
    refresh_token['user_id'] = str(user.id)
    refresh_token['tokenId'] = str(token_id)
    refresh_token['email'] = user.email
    
    # Set expiration
    if expires_in:
        refresh_token.set_exp(lifetime=expires_in)
    
    # Return token string
    return str(refresh_token)


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT access token.
    
    Args:
        token: JWT access token string
    
    Returns:
        Optional[Dict]: Decoded token payload if valid, None otherwise
    
    Note:
        Returns None for invalid, expired, or malformed tokens
    """
    if not token or not isinstance(token, str):
        return None
    
    try:
        # Decode and verify token
        access_token = AccessToken(token)
        
        # Get payload
        payload = access_token.payload
        
        # Validate required claims
        if 'user_id' not in payload:
            return None
        if 'email' not in payload:
            return None
        
        return payload
        
    except (TokenError, InvalidToken, KeyError, ValueError):
        # Token is invalid, expired, or malformed
        return None


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT refresh token.
    
    Args:
        token: JWT refresh token string
    
    Returns:
        Optional[Dict]: Decoded token payload if valid, None otherwise
    
    Note:
        Returns None for invalid, expired, or malformed tokens
    """
    if not token or not isinstance(token, str):
        return None
    
    try:
        # Decode and verify token
        refresh_token = RefreshToken(token)
        
        # Get payload
        payload = refresh_token.payload
        
        # Validate required claims
        if 'user_id' not in payload:
            return None
        if not all(key in payload for key in ['tokenId', 'email']):
            return None
        
        # Validate tokenId is a valid UUID
        try:
            uuid.UUID(payload['tokenId'])
        except (ValueError, TypeError):
            return None
        
        return payload
        
    except (TokenError, InvalidToken, KeyError, ValueError):
        # Token is invalid, expired, or malformed
        return None


def create_tokens_for_user(user: User, token_id: uuid.UUID) -> Dict[str, str]:
    """
    Create both access and refresh tokens for a user.
    
    Args:
        user: The user to create tokens for
        token_id: Unique identifier for the refresh token
    
    Returns:
        Dict: Dictionary with 'access_token' and 'refresh_token'
    """
    access_token = generate_access_token(user)
    refresh_token = generate_refresh_token(user, token_id)
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token
    }


def get_token_hash(token: str) -> str:
    """
    Generate a hash for a JWT token for storage in the database.
    
    Args:
        token: JWT token string
    
    Returns:
        str: SHA256 hash of the token
    """
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()
