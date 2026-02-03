"""Azure AD (Entra ID) identity provider implementation."""

from urllib.parse import urlencode

import httpx

from app.cloud.interfaces import (
    IdentityProvider,
    UserInfo,
    TokenResponse,
)
from app.config import get_settings
from app.tracing import Session, FunctionTrace


class AzureADIdentityProvider(IdentityProvider):
    """Azure AD (Entra ID) OAuth implementation of IdentityProvider.

    Supports both single-tenant and multi-tenant configurations.
    Uses the Microsoft identity platform v2.0 endpoints.

    Note on Azure scopes: Azure doesn't allow mixing scopes from different
    resources in a single token. The initial login gets Graph API scopes
    for user verification. Cloud resource scopes are obtained via token
    refresh when needed:
    - https://management.azure.com/.default (ARM for VMs, resource groups)
    - https://storage.azure.com/.default (Blob storage)
    - https://vault.azure.net/.default (Key Vault)
    """

    # Identity scopes for login - includes offline_access for refresh token
    IDENTITY_SCOPES = [
        "openid",
        "email",
        "profile",
        "offline_access",
        "User.Read",
    ]

    # Resource-specific scopes (obtained via refresh token when needed)
    ARM_SCOPE = "https://management.azure.com/.default"
    STORAGE_SCOPE = "https://storage.azure.com/.default"
    KEYVAULT_SCOPE = "https://vault.azure.net/.default"

    def __init__(self):
        settings = get_settings()
        self.client_id = settings.azure_client_id
        self.client_secret = settings.azure_client_secret
        self.tenant_id = getattr(settings, "azure_tenant_id", "common")

        # Build endpoint URLs
        # Use "common" for multi-tenant, or specific tenant ID for single-tenant
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.authorize_url = f"{self.authority}/oauth2/v2.0/authorize"
        self.token_url = f"{self.authority}/oauth2/v2.0/token"
        self.graph_url = "https://graph.microsoft.com/v1.0/me"

    def get_auth_url(
        self, redirect_uri: str, state: str, session: Session | None = None
    ) -> str:
        """Get the Azure AD OAuth authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.IDENTITY_SCOPES),
            "state": state,
            "response_mode": "query",
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_code(
        self, code: str, redirect_uri: str, session: Session | None = None
    ) -> TokenResponse:
        """Exchange authorization code for tokens."""
        with FunctionTrace(session, "Exchanging authorization code for tokens") as trace:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                        "scope": " ".join(self.IDENTITY_SCOPES),
                    },
                )
                response.raise_for_status()
                data = response.json()

            trace.log("Token exchange successful")

            return TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_in=data["expires_in"],
                token_type=data.get("token_type", "Bearer"),
            )

    async def verify_token(
        self, token: str, session: Session | None = None
    ) -> UserInfo:
        """Verify an access token and return user info.

        Uses Microsoft Graph API to get user information.
        """
        with FunctionTrace(session, "Verifying token via Microsoft Graph API") as trace:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.graph_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                data = response.json()

            trace.log("Token verified successfully")

            # Microsoft Graph returns different field names
            return UserInfo(
                subject=data["id"],  # Azure AD object ID
                email=data.get("mail") or data.get("userPrincipalName", ""),
                name=data.get("displayName", data.get("userPrincipalName", "")),
                picture=None,  # Graph API requires separate call for photo
            )

    async def refresh_token(
        self, refresh_token: str, session: Session | None = None
    ) -> TokenResponse:
        """Refresh an access token using identity scopes."""
        return await self.refresh_token_for_scope(
            refresh_token, " ".join(self.IDENTITY_SCOPES), session=session
        )

    async def refresh_token_for_scope(
        self, refresh_token: str, scope: str, session: Session | None = None
    ) -> TokenResponse:
        """Refresh an access token for a specific scope/resource.

        Use this to get tokens for specific Azure resources:
        - ARM_SCOPE for compute/resource management
        - STORAGE_SCOPE for blob storage
        - KEYVAULT_SCOPE for Key Vault
        """
        with FunctionTrace(session, "Refreshing token for scope", scope=scope) as trace:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                        "scope": scope,
                    },
                )
                response.raise_for_status()
                data = response.json()

            trace.log("Token refreshed successfully", scope=scope)

            return TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", refresh_token),
                expires_in=data["expires_in"],
                token_type=data.get("token_type", "Bearer"),
            )
