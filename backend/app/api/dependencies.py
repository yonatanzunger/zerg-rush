"""API dependencies for authentication and database access."""

from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.models import User, AuditLog, UserOAuthToken
from app.cloud.factory import get_providers, get_cloud_providers, CloudProviders
from app.cloud.interfaces import UserCredentials
from app.services import token_service, TokenNotFoundError
from app.tracing import EventTracer, Session

settings = get_settings()
security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get the current authenticated user from JWT token."""
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    # Get user from database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


# Type alias for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def log_action(
    db: AsyncSession,
    user_id: str,
    action_type: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Log an action to the audit log."""
    log_entry = AuditLog(
        id=str(uuid4()),
        user_id=user_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(log_entry)
    await db.flush()


def get_client_ip(request: Request) -> str | None:
    """Get the client IP address from the request."""
    # Check for forwarded headers (when behind a proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def get_user_credentials(
    current_user: CurrentUser,
    db: DbSession,
) -> UserCredentials:
    """Get user's cloud credentials from their stored OAuth token.

    This retrieves and validates the user's OAuth token, refreshing it
    if needed, and returns credentials for cloud operations.

    Raises:
        HTTPException 403: If user has no cloud credentials.
    """
    provider = settings.cloud_provider

    try:
        access_token = await token_service.get_valid_token(
            db, current_user.id, provider
        )
    except TokenNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No {provider} cloud credentials found. Please re-authenticate.",
        )

    # Get additional metadata from stored token
    result = await db.execute(
        select(UserOAuthToken).where(
            UserOAuthToken.user_id == current_user.id,
            UserOAuthToken.provider == provider,
        )
    )
    token_record = result.scalar_one()

    return UserCredentials(
        access_token=access_token,
        project_id=token_record.project_id,
        subscription_id=token_record.subscription_id,
        tenant_id=token_record.tenant_id,
        resource_group=settings.azure_resource_group if provider == "azure" else None,
    )


async def get_cloud_providers_for_user(
    user_credentials: Annotated[UserCredentials, Depends(get_user_credentials)],
) -> CloudProviders:
    """Get cloud providers configured with user credentials.

    Use this dependency for routes that perform cloud operations
    on behalf of the user.
    """
    return get_cloud_providers(user_credentials)


# Type aliases for dependency injection
UserCreds = Annotated[UserCredentials, Depends(get_user_credentials)]
UserCloudProviders = Annotated[CloudProviders, Depends(get_cloud_providers_for_user)]


def get_trace_session(request: Request) -> Session:
    """Create a trace session for the current request.

    The session is stored in request.state for middleware access.
    User information should be set via session.set_user() after authentication.
    """
    tracer = EventTracer.get_instance()
    session = tracer.create_session(
        client_ip=get_client_ip(request),
        request_path=str(request.url.path),
        request_method=request.method,
    )
    request.state.trace_session = session
    return session


TraceSession = Annotated[Session, Depends(get_trace_session)]
