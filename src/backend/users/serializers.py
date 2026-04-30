"""
Serializers for the users app.

This module contains DRF serializers for user authentication and profile operations.
"""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from rest_framework import serializers

from users.models import User


class RegisterSerializer(serializers.Serializer):
    """
    Serializer for user registration (POST /auth/register).

    Validates email uniqueness (case-insensitive), password strength
    via Django's built-in password validators, and optional full_name.
    """
    email = serializers.EmailField(required=True, max_length=255)
    password = serializers.CharField(required=True, write_only=True, min_length=8)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255, trim_whitespace=True)

    def validate_email(self, value: str) -> str:
        """
        Validate email uniqueness (case-insensitive).

        Args:
            value: The email string to validate

        Returns:
            The validated email string

        Raises:
            serializers.ValidationError: If email already exists
        """
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already exists")
        return value

    def validate_password(self, value: str) -> str:
        """
        Apply Django's built-in password validators from settings.

        Args:
            value: The password string to validate

        Returns:
            The validated password string

        Raises:
            serializers.ValidationError: If password fails validation
        """
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value


class LoginSerializer(serializers.Serializer):
    """
    Serializer for user login (POST /auth/login).

    Validates that email and password are provided.
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class UserSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for user data output.

    Used by register, login, and profile views to return consistent
    user data in responses.
    """
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']


class ProfileUpdateSerializer(serializers.Serializer):
    """
    Serializer for partial profile updates (PATCH /users/me).

    Validates optional fields: full_name and email.
    Email validation includes format check and uniqueness check.
    """
    full_name = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
        trim_whitespace=True,
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=False,
        max_length=255,
    )

    def validate_email(self, value: str) -> str:
        """
        Validate email format and uniqueness.

        Args:
            value: The email string to validate

        Returns:
            The validated email string

        Raises:
            serializers.ValidationError: If email format is invalid or already exists
        """
        # Validate email format using Django's built-in validator
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError("Invalid email format")

        # Check email uniqueness (excluding current user)
        user = self.context.get('user')
        if user and value.lower() == user.email.lower():
            return value  # Same email, no conflict

        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already exists")

        return value

    def validate_full_name(self, value: str) -> str:
        """
        Validate and clean full_name.

        Args:
            value: The full_name string to validate

        Returns:
            The validated and stripped full_name string
        """
        return value.strip()
