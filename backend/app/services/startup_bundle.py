"""Startup bundle service for secure credential delivery to VMs."""

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.cloud.interfaces import SecretProvider, StorageProvider
from app.models import AgentConfig, ChannelCredential
from app.tracing import Session


@dataclass
class StartupBundle:
    """Contains all data needed for VM startup."""

    config_json: str  # Resolved openclaw.json content
    env_vars: dict[str, str]  # Environment variable name -> value
    channel_credentials: dict[str, str]  # channel_type -> base64-encoded creds


@dataclass
class BundleUploadResult:
    """Result of uploading a startup bundle."""

    signed_url: str  # URL to download the bundle
    decryption_key: str  # Base64-encoded decryption key


class StartupBundleService:
    """Manages encrypted credential bundles for VM startup.

    This service is responsible for:
    - Collecting and resolving credentials from secret manager
    - Creating encrypted bundles
    - Uploading bundles to cloud storage
    - Generating signed URLs for download
    - Cleaning up bundles after successful startup
    """

    BUNDLE_KEY = "credentials/startup-bundle.enc"

    def __init__(
        self,
        secret_provider: SecretProvider,
        storage_provider: StorageProvider,
    ):
        self.secret_provider = secret_provider
        self.storage_provider = storage_provider

    async def create_bundle(
        self,
        agent_id: str,
        bucket_id: str,
        config: AgentConfig,
        channel_credentials: list[ChannelCredential],
        session: Session | None = None,
    ) -> BundleUploadResult:
        """Create and upload an encrypted startup bundle.

        Args:
            agent_id: The agent ID
            bucket_id: The storage bucket ID
            config: The agent configuration
            channel_credentials: List of channel credentials
            session: Optional session for logging

        Returns:
            BundleUploadResult with signed URL and decryption key
        """
        # Resolve config to final JSON
        config_json = await self._resolve_config(config)

        # Resolve environment variables
        env_vars = await self._resolve_env_vars(config)

        # Resolve channel credentials
        channel_creds = await self._resolve_channel_credentials(channel_credentials)

        # Create bundle
        bundle = StartupBundle(
            config_json=config_json,
            env_vars=env_vars,
            channel_credentials=channel_creds,
        )

        # Serialize and encrypt
        bundle_data = self._serialize_bundle(bundle)
        encryption_key = secrets.token_bytes(32)  # AES-256
        encrypted_data = self._encrypt_bundle(bundle_data, encryption_key)

        # Upload to storage
        await self.storage_provider.upload_object(
            bucket_id=bucket_id,
            key=self.BUNDLE_KEY,
            data=encrypted_data,
            session=session,
        )

        # Generate signed URL (10 minute expiry)
        signed_url = await self.storage_provider.get_signed_url(
            bucket_id=bucket_id,
            key=self.BUNDLE_KEY,
            expires_in=600,
            session=session,
        )

        return BundleUploadResult(
            signed_url=signed_url,
            decryption_key=base64.b64encode(encryption_key).decode(),
        )

    async def cleanup_bundle(
        self,
        bucket_id: str,
        session: Session | None = None,
    ) -> None:
        """Delete the startup bundle from storage after successful startup.

        Args:
            bucket_id: The storage bucket ID
            session: Optional session for logging
        """
        try:
            await self.storage_provider.delete_object(
                bucket_id=bucket_id,
                key=self.BUNDLE_KEY,
                session=session,
            )
        except Exception:
            # Ignore errors - bundle might already be deleted
            pass

    async def _resolve_config(self, config: AgentConfig) -> str:
        """Resolve config template to final JSON with secrets."""
        config_template = config.config_template.copy()

        # Resolve environment variable placeholders in config
        config_str = json.dumps(config_template, indent=2)
        for env_var, secret_ref in (config.env_var_refs or {}).items():
            try:
                value = await self.secret_provider.get_secret(secret_ref)
                # Escape for JSON
                escaped = json.dumps(value)[1:-1]
                config_str = config_str.replace(f"${{{env_var}}}", escaped)
            except Exception:
                # Leave placeholder if secret can't be resolved
                pass

        return config_str

    async def _resolve_env_vars(self, config: AgentConfig) -> dict[str, str]:
        """Resolve all environment variables from secret refs."""
        env_vars: dict[str, str] = {}

        for env_var, secret_ref in (config.env_var_refs or {}).items():
            try:
                value = await self.secret_provider.get_secret(secret_ref)
                env_vars[env_var] = value
            except Exception:
                # Skip env vars that can't be resolved
                pass

        return env_vars

    async def _resolve_channel_credentials(
        self, credentials: list[ChannelCredential]
    ) -> dict[str, str]:
        """Resolve channel credentials to base64-encoded data."""
        result: dict[str, str] = {}

        for cred in credentials:
            if cred.is_paired and cred.credentials_secret_ref:
                try:
                    value = await self.secret_provider.get_secret(
                        cred.credentials_secret_ref
                    )
                    # Base64 encode for transport
                    result[cred.channel_type] = base64.b64encode(
                        value.encode()
                    ).decode()
                except Exception:
                    # Skip credentials that can't be resolved
                    pass

        return result

    def _serialize_bundle(self, bundle: StartupBundle) -> bytes:
        """Serialize bundle to JSON bytes."""
        data = {
            "config_json": bundle.config_json,
            "env_vars": bundle.env_vars,
            "channel_credentials": bundle.channel_credentials,
        }
        return json.dumps(data).encode()

    def _encrypt_bundle(self, data: bytes, key: bytes) -> bytes:
        """Encrypt bundle using AES-256-GCM.

        Args:
            data: The plaintext data to encrypt
            key: 32-byte encryption key

        Returns:
            Encrypted data with 12-byte nonce prepended
        """
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext

    @staticmethod
    def decrypt_bundle(encrypted_data: bytes, key_b64: str) -> StartupBundle:
        """Decrypt a startup bundle.

        This is a static method that can be used on the VM side
        to decrypt the downloaded bundle.

        Args:
            encrypted_data: The encrypted bundle data
            key_b64: Base64-encoded decryption key

        Returns:
            The decrypted StartupBundle
        """
        key = base64.b64decode(key_b64)
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        data = json.loads(plaintext)
        return StartupBundle(
            config_json=data["config_json"],
            env_vars=data["env_vars"],
            channel_credentials=data["channel_credentials"],
        )


def generate_bundle_download_script(signed_url: str, decryption_key: str) -> str:
    """Generate a bash script snippet to download and extract the startup bundle.

    This script is included in the VM startup script to:
    1. Download the encrypted bundle via signed URL
    2. Decrypt it using the provided key
    3. Extract config and credentials to appropriate locations
    4. Clean up the encrypted bundle

    Args:
        signed_url: Signed URL to download the bundle
        decryption_key: Base64-encoded decryption key

    Returns:
        Bash script snippet
    """
    return f'''
# Download and decrypt startup bundle
BUNDLE_URL="{signed_url}"
DECRYPTION_KEY="{decryption_key}"

# Download bundle
curl -s -o /tmp/startup-bundle.enc "$BUNDLE_URL"

# Decrypt and extract using Python
python3 << 'DECRYPT_SCRIPT'
import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Read encrypted data
with open('/tmp/startup-bundle.enc', 'rb') as f:
    encrypted_data = f.read()

# Decrypt
key = base64.b64decode("{decryption_key}")
nonce = encrypted_data[:12]
ciphertext = encrypted_data[12:]
aesgcm = AESGCM(key)
plaintext = aesgcm.decrypt(nonce, ciphertext, None)

# Parse bundle
bundle = json.loads(plaintext)

# Write config
os.makedirs(os.path.expanduser('~/.openclaw'), exist_ok=True)
with open(os.path.expanduser('~/.openclaw/openclaw.json'), 'w') as f:
    f.write(bundle['config_json'])

# Write env vars
env_lines = []
for name, value in bundle['env_vars'].items():
    # Escape for bash
    escaped = value.replace("'", "'\"'\"'")
    env_lines.append(f"export {{name}}='{{escaped}}'")

with open(os.path.expanduser('~/.openclaw/.env'), 'w') as f:
    f.write('\\n'.join(env_lines))

# Write channel credentials
for channel, creds_b64 in bundle['channel_credentials'].items():
    creds_dir = os.path.expanduser(f'~/.openclaw/credentials/{{channel}}/default')
    os.makedirs(creds_dir, exist_ok=True)
    creds_data = base64.b64decode(creds_b64)
    with open(os.path.join(creds_dir, 'creds.json'), 'wb') as f:
        f.write(creds_data)

print('Bundle extracted successfully')
DECRYPT_SCRIPT

# Clean up
rm -f /tmp/startup-bundle.enc

# Source env vars
source ~/.openclaw/.env
'''
