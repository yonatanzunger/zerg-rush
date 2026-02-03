"""Azure AD (Entra ID) identity provider implementation."""

from urllib.parse import urlencode

import httpx

from app.cloud.interfaces import (
    IdentityProvider,
    UserInfo,
    TokenResponse,
)
from app.config import get_settings


class AzureADIdentityProvider(IdentityProvider):
    """Azure AD (Entra ID) OAuth implementation of IdentityProvider.

    Supports both single-tenant and multi-tenant configurations.
    Uses the Microsoft identity platform v2.0 endpoints.
    """

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

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Get the Azure AD OAuth authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile User.Read",
            "state": state,
            "response_mode": "query",
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange authorization code for tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "scope": "openid email profile User.Read",
                },
            )
            response.raise_for_status()
            data = response.json()

        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data["expires_in"],
            token_type=data.get("token_type", "Bearer"),
        )

    async def verify_token(self, token: str) -> UserInfo:
        """Verify an access token and return user info.

        Uses Microsoft Graph API to get user information.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.graph_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()

        # Microsoft Graph returns different field names
        return UserInfo(
            subject=data["id"],  # Azure AD object ID
            email=data.get("mail") or data.get("userPrincipalName", ""),
            name=data.get("displayName", data.get("userPrincipalName", "")),
            picture=None,  # Graph API requires separate call for photo
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an access token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "openid email profile User.Read",
                },
            )
            response.raise_for_status()
            data = response.json()

        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_in=data["expires_in"],
            token_type=data.get("token_type", "Bearer"),
        )
