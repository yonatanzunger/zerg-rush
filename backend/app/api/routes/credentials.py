"""Credentials management routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession, log_action, get_client_ip, UserCloudProviders
from app.cloud.factory import get_providers, CloudProviders
from app.models import Credential

router = APIRouter()


class CreateCredentialRequest(BaseModel):
    """Request to create a new credential."""

    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["llm", "cloud", "utility"]
    description: str | None = None
    value: str = Field(..., min_length=1)


class CredentialResponse(BaseModel):
    """Credential response (without the secret value)."""

    id: str
    name: str
    type: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class CredentialListResponse(BaseModel):
    """List of credentials response."""

    credentials: list[CredentialResponse]
    total: int


@router.get("", response_model=CredentialListResponse)
async def list_credentials(
    current_user: CurrentUser,
    db: DbSession,
    type_filter: Annotated[str | None, Query(alias="type")] = None,
) -> CredentialListResponse:
    """List all credentials for the current user."""
    query = select(Credential).where(Credential.user_id == current_user.id)

    if type_filter:
        query = query.where(Credential.type == type_filter)

    result = await db.execute(query.order_by(Credential.name))
    credentials = result.scalars().all()

    return CredentialListResponse(
        credentials=[CredentialResponse.model_validate(c) for c in credentials],
        total=len(credentials),
    )


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    body: CreateCredentialRequest,
) -> Credential:
    """Create a new credential (stores secret in keyvault)."""

    # Store secret in keyvault
    try:
        secret_ref = await providers.secret.store_secret(
            user_id=current_user.id,
            name=body.name,
            value=body.value,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store secret: {str(e)}",
        )

    # Create credential record
    credential = Credential(
        id=str(uuid4()),
        user_id=current_user.id,
        name=body.name,
        type=body.type,
        description=body.description,
        secret_ref=secret_ref,
    )
    db.add(credential)

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="credential.create",
        target_type="credential",
        target_id=credential.id,
        details={"name": body.name, "type": body.type},
        ip_address=get_client_ip(request),
    )

    await db.commit()
    await db.refresh(credential)

    return credential


@router.get("/{credential_id}", response_model=CredentialResponse)
async def get_credential(
    current_user: CurrentUser,
    db: DbSession,
    credential_id: str,
) -> Credential:
    """Get a specific credential by ID."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.user_id == current_user.id,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    return credential


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    providers: UserCloudProviders,
    credential_id: str,
) -> None:
    """Delete a credential (removes from keyvault and database)."""

    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.user_id == current_user.id,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    # Delete from keyvault
    try:
        await providers.secret.delete_secret(credential.secret_ref)
    except Exception as e:
        # Log but continue - secret might already be deleted
        pass

    # Log action
    await log_action(
        db=db,
        user_id=current_user.id,
        action_type="credential.delete",
        target_type="credential",
        target_id=credential_id,
        details={"name": credential.name, "type": credential.type},
        ip_address=get_client_ip(request),
    )

    # Delete from database
    await db.delete(credential)
    await db.commit()
