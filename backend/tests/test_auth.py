"""Tests for authentication routes."""

import unittest
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app.config import get_settings
from app.models import User
from tests.base import AsyncTestCase


class TestHealthCheck(AsyncTestCase):
    """Tests for the health check endpoint."""

    async def test_health_check(self):
        """Test that health check returns healthy status."""
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)


class TestLogin(AsyncTestCase):
    """Tests for the login flow."""

    async def test_login_redirects_to_oauth(self):
        """Test that login redirects to OAuth provider."""
        response = await self.client.get("/auth/login", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertIn("auth.example.com", response.headers["location"])

    async def test_login_sets_state_cookie(self):
        """Test that login sets CSRF state cookie."""
        response = await self.client.get("/auth/login", follow_redirects=False)
        self.assertIn("oauth_state", response.cookies)

    async def test_login_rejects_arbitrary_redirect_uri(self):
        """Test that login rejects redirect URIs not in the whitelist."""
        response = await self.client.get(
            "/auth/login",
            params={"redirect_uri": "https://evil.com/steal-tokens"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("not in the allowed list", data["detail"])

    async def test_login_accepts_default_redirect_uri(self):
        """Test that login accepts the default redirect URI."""
        settings = get_settings()
        response = await self.client.get(
            "/auth/login",
            params={"redirect_uri": settings.oauth_redirect_uri},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 307)


class TestOAuthCallback(AsyncTestCase):
    """Tests for OAuth callback handling."""

    async def test_callback_creates_new_user(self):
        """Test that OAuth callback creates a new user."""
        # Delete the default test user first so we can test user creation
        await self.session.delete(self.test_user)
        await self.session.commit()

        response = await self.client.get(
            "/auth/callback",
            params={"code": "test-code", "state": "test-state"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 307)
        self.assertIn("token=", response.headers["location"])

        result = await self.session.execute(
            select(User).where(User.email == "test@example.com")
        )
        user = result.scalar_one_or_none()
        self.assertIsNotNone(user)
        self.assertEqual(user.oauth_provider, "google")

    async def test_callback_updates_existing_user(self):
        """Test that OAuth callback updates last_login for existing user."""
        old_login = self.test_user.last_login

        response = await self.client.get(
            "/auth/callback",
            params={"code": "test-code", "state": "test-state"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 307)

        await self.session.refresh(self.test_user)
        self.assertGreaterEqual(self.test_user.last_login, old_login)


class TestCurrentUser(AsyncTestCase):
    """Tests for the current user endpoint."""

    async def test_get_current_user_requires_auth(self):
        """Test that /me requires authentication."""
        response = await self.client.get("/auth/me")
        self.assertEqual(response.status_code, 403)

    async def test_get_current_user_returns_user_info(self):
        """Test that /me returns current user info."""
        response = await self.auth_client.get("/auth/me")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["id"], self.test_user.id)
        self.assertEqual(data["email"], self.test_user.email)
        self.assertEqual(data["name"], self.test_user.name)


class TestLogout(AsyncTestCase):
    """Tests for the logout endpoint."""

    async def test_logout_requires_auth(self):
        """Test that logout requires authentication."""
        response = await self.client.post("/auth/logout")
        self.assertEqual(response.status_code, 403)

    async def test_logout_success(self):
        """Test successful logout."""
        response = await self.auth_client.post("/auth/logout")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Logged out successfully")


class TestTokenValidation(AsyncTestCase):
    """Tests for JWT token validation."""

    async def test_invalid_token_rejected(self):
        """Test that invalid tokens are rejected."""
        response = await self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        self.assertEqual(response.status_code, 401)

    async def test_expired_token_rejected(self):
        """Test that expired tokens are rejected."""
        settings = get_settings()
        expired_payload = {
            "sub": "some-user-id",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = jwt.encode(expired_payload, settings.secret_key, algorithm="HS256")

        response = await self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        self.assertEqual(response.status_code, 401)

    async def test_token_with_nonexistent_user_rejected(self):
        """Test that tokens for non-existent users are rejected."""
        from app.api.routes.auth import create_access_token

        token = create_access_token("nonexistent-user-id")
        response = await self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
