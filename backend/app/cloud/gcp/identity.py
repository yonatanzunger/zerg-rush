"""Google OAuth identity provider implementation."""

from urllib.parse import urlencode

import httpx
from google.oauth2 import id_token
from google.auth.transport import requests

from app.cloud.interfaces import (
    IdentityProvider,
    UserInfo,
    TokenResponse,
)
from app.config import get_settings


class GoogleIdentityProvider(IdentityProvider):
    """Google OAuth implementation of IdentityProvider."""

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    # OAuth scopes for identity and cloud operations
    # - openid, email, profile: User identity
    # - cloud-platform: Full access to GCP APIs (compute, storage, secrets, etc.)
    SCOPES = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/cloud-platform",
    ]

    def __init__(self):
        settings = get_settings()
        self.client_id = settings.google_client_id
        self.client_secret = settings.google_client_secret

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Get the Google OAuth authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self, code: str, redirect_uri: str
    ) -> TokenResponse:
        """Exchange authorization code for tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
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
        """Verify an access token and return user info."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()

        return UserInfo(
            subject=data["sub"],
            email=data["email"],
            name=data.get("name", data["email"]),
            picture=data.get("picture"),
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an access token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
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
