"""
Serializers for the users app.

This module contains DRF serializers for user profile operations.
"""
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from rest_framework import serializers

from users.models import User


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
