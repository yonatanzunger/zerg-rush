"""Token service for retrieving and refreshing OAuth tokens."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cloud.gcp.identity import GoogleIdentityProvider
from app.cloud.azure.identity import AzureADIdentityProvider
from app.config import get_settings
from app.models import UserOAuthToken
from app.services.encryption import encrypt_token, decrypt_token


class TokenNotFoundError(Exception):
    """Raised when no OAuth token is found for a user."""

    pass


class TokenRefreshError(Exception):
    """Raised when token refresh fails."""

    pass


class TokenService:
    """Service for managing user OAuth tokens.

    Handles token retrieval, validation, and automatic refresh.
    """

    # Refresh tokens when they expire within this window
    REFRESH_BUFFER = timedelta(minutes=5)

    async def get_valid_token(
        self,
        db: AsyncSession,
        user_id: str,
        provider: Literal["gcp", "azure"],
        resource_scope: str | None = None,
    ) -> str:
        """Get a valid access token for the user, refreshing if needed.

        Args:
            db: Database session.
            user_id: The user's ID.
            provider: Cloud provider ("gcp" or "azure").
            resource_scope: For Azure, the specific resource scope needed.
                If None, returns the identity token.

        Returns:
            A valid access token.

        Raises:
            TokenNotFoundError: If no token exists for the user.
            TokenRefreshError: If token refresh fails.
        """
        token_record = await self._get_user_token(db, user_id, provider)
        if not token_record:
            raise TokenNotFoundError(
                f"No {provider} OAuth token found for user. Please re-authenticate."
            )

        # Check if token needs refresh
        now = datetime.now(timezone.utc)
        if token_record.expires_at <= now + self.REFRESH_BUFFER:
            token_record = await self._refresh_token(
                db, token_record, provider, resource_scope
            )

        return decrypt_token(token_record.access_token_encrypted)

    async def get_token_for_resource(
        self,
        db: AsyncSession,
        user_id: str,
        resource_scope: str,
    ) -> str:
        """Get an access token for a specific Azure resource.

        Azure requires separate tokens for different resources (ARM, Storage, KeyVault).
        This method exchanges the refresh token for a token with the specified scope.

        Args:
            db: Database session.
            user_id: The user's ID.
            resource_scope: The Azure resource scope (e.g., AzureADIdentityProvider.ARM_SCOPE).

        Returns:
            An access token valid for the specified resource.
        """
        settings = get_settings()
        if settings.cloud_provider != "azure":
            raise ValueError("get_token_for_resource is only for Azure")

        token_record = await self._get_user_token(db, user_id, "azure")
        if not token_record:
            raise TokenNotFoundError(
                "No Azure OAuth token found for user. Please re-authenticate."
            )

        # For Azure, we always refresh with the specific scope to get a resource token
        refresh_token = decrypt_token(token_record.refresh_token_encrypted)

        identity_provider = AzureADIdentityProvider()
        try:
            new_tokens = await identity_provider.refresh_token_for_scope(
                refresh_token, resource_scope
            )
        except Exception as e:
            raise TokenRefreshError(f"Failed to get token for resource: {e}")

        # Note: We don't update the stored token because it's for a different resource
        # The stored token is for Graph API (identity), not the requested resource
        return new_tokens.access_token

    async def _get_user_token(
        self,
        db: AsyncSession,
        user_id: str,
        provider: str,
    ) -> UserOAuthToken | None:
        """Get the user's OAuth token record from the database."""
        result = await db.execute(
            select(UserOAuthToken).where(
                UserOAuthToken.user_id == user_id,
                UserOAuthToken.provider == provider,
            )
        )
        return result.scalar_one_or_none()

    async def _refresh_token(
        self,
        db: AsyncSession,
        token_record: UserOAuthToken,
        provider: str,
        resource_scope: str | None = None,
    ) -> UserOAuthToken:
        """Refresh an expired or expiring token.

        Args:
            db: Database session.
            token_record: The existing token record.
            provider: Cloud provider.
            resource_scope: For Azure, specific resource scope (optional).

        Returns:
            The updated token record.
        """
        refresh_token = decrypt_token(token_record.refresh_token_encrypted)

        # Get the appropriate identity provider
        if provider == "gcp":
            identity_provider = GoogleIdentityProvider()
            new_tokens = await identity_provider.refresh_token(refresh_token)
        else:
            identity_provider = AzureADIdentityProvider()
            if resource_scope:
                new_tokens = await identity_provider.refresh_token_for_scope(
                    refresh_token, resource_scope
                )
            else:
                new_tokens = await identity_provider.refresh_token(refresh_token)

        try:
            # Update the token record
            token_record.access_token_encrypted = encrypt_token(new_tokens.access_token)
            if new_tokens.refresh_token:
                token_record.refresh_token_encrypted = encrypt_token(
                    new_tokens.refresh_token
                )
            token_record.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=new_tokens.expires_in
            )

            await db.commit()
            await db.refresh(token_record)

            return token_record
        except Exception as e:
            await db.rollback()
            raise TokenRefreshError(f"Failed to refresh token: {e}")

    async def has_valid_token(
        self,
        db: AsyncSession,
        user_id: str,
        provider: str,
    ) -> bool:
        """Check if user has a valid (or refreshable) OAuth token.

        Args:
            db: Database session.
            user_id: The user's ID.
            provider: Cloud provider.

        Returns:
            True if user has a token (even if expired, as long as refresh token exists).
        """
        token_record = await self._get_user_token(db, user_id, provider)
        return token_record is not None

    async def get_token_info(
        self,
        db: AsyncSession,
        user_id: str,
        provider: str,
    ) -> dict | None:
        """Get information about the user's OAuth token.

        Returns non-sensitive metadata about the token.
        """
        token_record = await self._get_user_token(db, user_id, provider)
        if not token_record:
            return None

        now = datetime.now(timezone.utc)
        return {
            "provider": token_record.provider,
            "expires_at": token_record.expires_at.isoformat(),
            "is_expired": token_record.expires_at <= now,
            "needs_refresh": token_record.expires_at <= now + self.REFRESH_BUFFER,
            "project_id": token_record.project_id,
            "subscription_id": token_record.subscription_id,
            "tenant_id": token_record.tenant_id,
        }


# Singleton instance
token_service = TokenService()
