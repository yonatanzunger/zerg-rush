"""Authentication routes."""

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
from app.config import get_settings
from app.db.session import get_db
from app.models import User

router = APIRouter()
settings = get_settings()


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

    # Use provided redirect URI or default
    callback_uri = redirect_uri or settings.oauth_redirect_uri

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

    # Find or create user
    result = await db.execute(
        select(User).where(
            User.oauth_provider == "google",
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
            oauth_provider="google",
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
            details={"email": user.email, "provider": "google"},
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

    await db.commit()

    # Create JWT token
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
