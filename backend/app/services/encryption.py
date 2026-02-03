"""Token encryption service for secure OAuth token storage."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _get_fernet() -> Fernet:
    """Get or create a Fernet instance for token encryption.

    Uses TOKEN_ENCRYPTION_KEY if set, otherwise derives a key from SECRET_KEY.
    """
    settings = get_settings()

    if settings.token_encryption_key:
        # Use explicit Fernet key
        key = settings.token_encryption_key.encode()
    else:
        # Derive a Fernet-compatible key from secret_key
        # SHA-256 produces 32 bytes, which we base64-encode for Fernet
        derived = hashlib.sha256(settings.secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(derived)

    return Fernet(key)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token for secure storage.

    Args:
        plaintext: The token value to encrypt.

    Returns:
        Base64-encoded encrypted token.
    """
    fernet = _get_fernet()
    encrypted = fernet.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored token.

    Args:
        ciphertext: The encrypted token from storage.

    Returns:
        The decrypted token value.

    Raises:
        cryptography.fernet.InvalidToken: If the token cannot be decrypted.
    """
    fernet = _get_fernet()
    decrypted = fernet.decrypt(ciphertext.encode())
    return decrypted.decode()
