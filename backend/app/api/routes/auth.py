"""Authentication routes."""

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from jose import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, DbSession, log_action
from app.cloud.factory import get_providers
from app.cloud.gcp.identity import GoogleIdentityProvider
from app.cloud.azure.identity import AzureADIdentityProvider
from app.config import get_settings
from app.db.session import get_db
from app.models import User, UserOAuthToken
from app.services.encryption import encrypt_token

router = APIRouter()
settings = get_settings()


def get_allowed_redirect_uris() -> set[str]:
    """Get the set of allowed OAuth redirect URIs.

    Returns:
        Set of allowed redirect URIs, always includes the default oauth_redirect_uri.
    """
    allowed = {settings.oauth_redirect_uri}
    if settings.allowed_oauth_redirect_uris:
        # Parse comma-separated list and add to allowed set
        for uri in settings.allowed_oauth_redirect_uris.split(","):
            uri = uri.strip()
            if uri:
                allowed.add(uri)
    return allowed


def validate_redirect_uri(redirect_uri: str | None) -> str:
    """Validate and return a safe redirect URI.

    Args:
        redirect_uri: The requested redirect URI, or None to use default.

    Returns:
        A validated redirect URI from the whitelist.

    Raises:
        HTTPException: If the redirect URI is not in the whitelist.
    """
    if redirect_uri is None:
        return settings.oauth_redirect_uri

    allowed = get_allowed_redirect_uris()
    if redirect_uri not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redirect_uri. The provided URI is not in the allowed list.",
        )
    return redirect_uri


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """User information response."""

    id: str
    email: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    if expires_delta is None:
        expires_delta = timedelta(hours=24)

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


@router.get("/login")
async def login(
    redirect_uri: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Initiate OAuth login flow."""
    providers = get_providers()

    # Validate redirect URI against whitelist
    callback_uri = validate_redirect_uri(redirect_uri)

    # Generate state for CSRF protection
    state = str(uuid4())

    # Get authorization URL
    auth_url = providers.identity.get_auth_url(
        redirect_uri=callback_uri,
        state=state,
    )

    # In production, store state in session/cache for verification
    response = RedirectResponse(url=auth_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=600,  # 10 minutes
    )

    return response


@router.get("/callback")
async def oauth_callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db: DbSession,
) -> RedirectResponse:
    """Handle OAuth callback."""
    providers = get_providers()

    # Determine OAuth provider from cloud configuration
    oauth_provider_name = "google" if settings.cloud_provider == "gcp" else "azure"

    # Exchange code for tokens
    try:
        token_response = await providers.identity.exchange_code(
            code=code,
            redirect_uri=settings.oauth_redirect_uri,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {str(e)}",
        )

    # Get user info
    try:
        user_info = await providers.identity.verify_token(token_response.access_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify token: {str(e)}",
        )

    # Determine scopes based on provider
    if oauth_provider_name == "google":
        scopes = GoogleIdentityProvider.SCOPES
    else:
        scopes = AzureADIdentityProvider.IDENTITY_SCOPES

    # Find or create user
    result = await db.execute(
        select(User).where(
            User.oauth_provider == oauth_provider_name,
            User.oauth_subject == user_info.subject,
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        # Create new user
        user = User(
            id=str(uuid4()),
            email=user_info.email,
            name=user_info.name,
            oauth_provider=oauth_provider_name,
            oauth_subject=user_info.subject,
            last_login=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.flush()

        await log_action(
            db=db,
            user_id=user.id,
            action_type="user.created",
            target_type="user",
            target_id=user.id,
            details={"email": user.email, "provider": oauth_provider_name},
        )
    else:
        # Update last login
        user.last_login = datetime.now(timezone.utc)

        await log_action(
            db=db,
            user_id=user.id,
            action_type="user.login",
            target_type="user",
            target_id=user.id,
        )

    # Store OAuth tokens for cloud operations
    # Calculate token expiration time
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_response.expires_in)

    # Check for existing OAuth token record
    result = await db.execute(
        select(UserOAuthToken).where(
            UserOAuthToken.user_id == user.id,
            UserOAuthToken.provider == settings.cloud_provider,
        )
    )
    existing_oauth_token = result.scalar_one_or_none()

    if existing_oauth_token:
        # Update existing token
        existing_oauth_token.access_token_encrypted = encrypt_token(token_response.access_token)
        if token_response.refresh_token:
            existing_oauth_token.refresh_token_encrypted = encrypt_token(token_response.refresh_token)
        existing_oauth_token.expires_at = expires_at
        existing_oauth_token.scopes = json.dumps(scopes)
    else:
        # Create new token record
        if not token_response.refresh_token:
            # Refresh token is required for cloud operations
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth provider did not return a refresh token. Please revoke app access and try again.",
            )

        oauth_token = UserOAuthToken(
            id=str(uuid4()),
            user_id=user.id,
            provider=settings.cloud_provider,
            access_token_encrypted=encrypt_token(token_response.access_token),
            refresh_token_encrypted=encrypt_token(token_response.refresh_token),
            token_type=token_response.token_type,
            expires_at=expires_at,
            scopes=json.dumps(scopes),
            # Cloud-specific metadata can be set later via user settings
            project_id=settings.gcp_project_id if settings.cloud_provider == "gcp" else None,
            subscription_id=settings.azure_subscription_id if settings.cloud_provider == "azure" else None,
            tenant_id=settings.azure_tenant_id if settings.cloud_provider == "azure" else None,
        )
        db.add(oauth_token)

    await db.commit()

    # Create JWT token for app authentication
    access_token = create_access_token(user.id)

    # Redirect to frontend with token
    redirect_url = f"{settings.frontend_url}/auth/callback?token={access_token}"
    return RedirectResponse(url=redirect_url)


@router.post("/logout")
async def logout(
    current_user: CurrentUser,
    db: DbSession,
) -> dict:
    """Log out the current user."""
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="user.logout",
        target_type="user",
        target_id=current_user.id,
    )
    await db.commit()

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser) -> User:
    """Get the current user's information."""
    return current_user


class CloudStatusResponse(BaseModel):
    """Cloud credentials status response."""

    connected: bool
    provider: str
    expires_at: datetime | None = None
    needs_refresh: bool = False
    project_id: str | None = None
    subscription_id: str | None = None


@router.get("/cloud-status", response_model=CloudStatusResponse)
async def get_cloud_status(
    current_user: CurrentUser,
    db: DbSession,
) -> CloudStatusResponse:
    """Check if the current user has valid cloud credentials.

    Returns information about the user's cloud OAuth token status.
    """
    provider = settings.cloud_provider

    result = await db.execute(
        select(UserOAuthToken).where(
            UserOAuthToken.user_id == current_user.id,
            UserOAuthToken.provider == provider,
        )
    )
    token = result.scalar_one_or_none()

    if not token:
        return CloudStatusResponse(
            connected=False,
            provider=provider,
        )

    now = datetime.now(timezone.utc)
    needs_refresh = token.expires_at <= now + timedelta(minutes=5)

    return CloudStatusResponse(
        connected=True,
        provider=provider,
        expires_at=token.expires_at,
        needs_refresh=needs_refresh,
        project_id=token.project_id,
        subscription_id=token.subscription_id,
    )
