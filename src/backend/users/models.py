"""
User models for the DocuChat system.
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom manager for User model."""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user."""
        if not email:
            raise ValueError('The Email field must be set')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class RefreshTokenManager(models.Manager):
    """
    Custom manager for RefreshToken model.
    Provides methods for common refresh token operations.
    """
    
    def create_refresh_token(self, user, token_hash, expires_at):
        """
        Create a new refresh token.
        
        Args:
            user: The user who owns the token
            token_hash: Hashed token value (must be unique)
            expires_at: Expiration datetime
            
        Returns:
            RefreshToken: The created refresh token
        """
        # Validate inputs
        if not user:
            raise ValueError('User must be provided')
        if not token_hash:
            raise ValueError('Token hash must be provided')
        if not expires_at:
            raise ValueError('Expiration time must be provided')
        
        # Create and save the token
        refresh_token = self.model(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at
        )
        refresh_token.save(using=self._db)
        return refresh_token
    
    def get_by_token_hash(self, token_hash):
        """
        Get a refresh token by its hash.
        
        Args:
            token_hash: The hashed token value to look up
            
        Returns:
            RefreshToken: The token if found
            
        Raises:
            RefreshToken.DoesNotExist: If token not found
        """
        return self.get(token_hash=token_hash)
    
    def get_valid_tokens_for_user(self, user):
        """
        Get all valid (non-expired) refresh tokens for a user.
        
        Args:
            user: The user to get tokens for
            
        Returns:
            QuerySet: QuerySet of valid refresh tokens
        """
        from django.utils import timezone
        
        # Get tokens that are not expired and belong to active user
        return self.filter(
            user=user,
            expires_at__gt=timezone.now(),  # Not expired
            user__is_active=True  # User is active
        ).order_by('-created_at')
    
    def cleanup_expired_tokens(self):
        """
        Delete all expired refresh tokens from the database.
        
        Returns:
            int: Number of tokens deleted
        """
        from django.utils import timezone
        
        # Get all expired tokens
        expired_tokens = self.filter(expires_at__lte=timezone.now())
        
        # Count before deletion
        count = expired_tokens.count()
        
        # Delete expired tokens
        expired_tokens.delete()
        
        return count
    
    def revoke_all_for_user(self, user):
        """
        Revoke (delete) all refresh tokens for a user.
        
        Args:
            user: The user whose tokens should be revoked
            
        Returns:
            int: Number of tokens revoked
        """
        # Get all tokens for user
        user_tokens = self.filter(user=user)
        
        # Count before deletion
        count = user_tokens.count()
        
        # Delete all tokens
        user_tokens.delete()
        
        return count
    
    def is_token_valid(self, token_hash):
        """
        Check if a token is valid by its hash.
        
        Args:
            token_hash: The hashed token value to check
            
        Returns:
            bool: True if token exists and is valid, False otherwise
        """
        try:
            token = self.get(token_hash=token_hash)
            return token.is_valid()
        except self.model.DoesNotExist:
            return False


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model that uses email as the unique identifier.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, max_length=255)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['email']),
        ]
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        """Return the user's full name."""
        return self.full_name or self.email
    
    def get_short_name(self):
        """Return the user's email."""
        return self.email
    
    def verify_password(self, raw_password):
        """
        Verify if the given raw password matches the user's hashed password.
        
        Args:
            raw_password (str): The raw password to verify
            
        Returns:
            bool: True if password matches, False otherwise
        """
        return self.check_password(raw_password)


class APIKey(models.Model):
    """
    API Key model for programmatic access.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    key_hash = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'api_keys'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['key_hash']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.user.email})"


class RefreshToken(models.Model):
    """
    Refresh Token model for JWT authentication.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='refresh_tokens')
    token_hash = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    
    objects = RefreshTokenManager()
    
    class Meta:
        db_table = 'refresh_tokens'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['token_hash']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"RefreshToken for {self.user.email} (expires: {self.expires_at})"
    
    def is_expired(self):
        """Check if the refresh token has expired."""
        from django.utils import timezone
        return timezone.now() >= self.expires_at
    
    def is_valid(self):
        """
        Comprehensive token validation.
        
        Returns:
            bool: True if token is valid (not expired and user is active), False otherwise
        """
        from django.utils import timezone
        
        # Check if token is expired
        if self.is_expired():
            return False
        
        # Check if user is active
        if not self.user.is_active:
            return False
        
        return True
    
    def get_remaining_lifetime(self):
        """
        Get the remaining lifetime of the token.
        
        Returns:
            datetime.timedelta: Time remaining until expiration
        """
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        if now >= self.expires_at:
            # Token is already expired, return zero or negative timedelta
            return timedelta(seconds=0)
        
        return self.expires_at - now
    
    def revoke(self):
        """
        Revoke (delete) the refresh token.
        
        This permanently removes the token from the database, making it unusable.
        """
        self.delete()
