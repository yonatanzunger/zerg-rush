"""OpenClaw agent platform implementation."""

from app.agents.base import AgentPlatform, StartupScriptConfig
from app.models.user import User


class OpenClawPlatform(AgentPlatform):
    """OpenClaw agent platform.

    OpenClaw is a Node.js-based agent platform that provides AI assistants
    with multi-channel messaging support (WhatsApp, Telegram, etc.).
    """

    @property
    def platform_type(self) -> str:
        return "openclaw"

    def get_startup_script(
        self,
        user: "User",
        version: str | None = None,
        config: StartupScriptConfig | None = None,
    ) -> str:
        """Get the startup script for OpenClaw platform.

        Args:
            user: The current user requesting the agent.
            version: Optional specific version to install. If None, installs latest.
            config: Optional startup script configuration with bundle URL and key.

        Returns:
            Bash startup script that installs and configures OpenClaw.
        """
        gateway_port = (
            config.gateway_port if config else self.get_default_gateway_port()
        )
        username = self._username_from_email(user.email)

        # Build the bundle download section if credentials are provided
        bundle_section = ""
        if config and config.bundle_url and config.decryption_key:
            bundle_section = self._get_bundle_download_script(
                config.bundle_url, config.decryption_key
            )

        version_arg = f"@{version}" if version else "@latest"

        return f"""#!/bin/bash
set -e

echo "=== OpenClaw VM Startup Script ==="
echo "Starting at $(date)"

# Update system and install dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y curl python3 python3-pip

# Install Python cryptography for bundle decryption
pip3 install cryptography --break-system-packages || pip3 install cryptography

# Create user if not exists
echo "Setting up user: {username}..."
useradd -m -s /bin/bash {username} 2>/dev/null || true

# Switch to user context for OpenClaw setup
sudo -u {username} bash << 'USERSCRIPT'
set -e
cd ~

# Create OpenClaw directories
mkdir -p ~/.openclaw/credentials
mkdir -p ~/.openclaw/workspace

{bundle_section}

echo "Setting up OpenClaw for user $USER..."
curl -fsSL https://openclaw.bot/install.sh | bash -s -- --no-onboard

# Run onboarding with daemon installation
echo "Running OpenClaw onboarding..."
openclaw onboard --install-daemon --no-prompt || true

# Start the gateway
echo "Starting OpenClaw gateway on port {gateway_port}..."
nohup openclaw gateway --port {gateway_port} > ~/.openclaw/gateway.log 2>&1 &

# Wait for gateway to start
sleep 5

# Mark setup as complete
touch ~/.openclaw/setup-complete
echo "OpenClaw setup complete!"

USERSCRIPT

# Set up systemd service for auto-restart
echo "Setting up systemd service..."
cat > /etc/systemd/system/openclaw.service << 'SYSTEMD'
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User={username}
WorkingDirectory=/home/{username}
Environment=PATH=/home/{username}/.local/share/pnpm:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/openclaw gateway --port {gateway_port}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable openclaw
systemctl start openclaw || true

echo "=== OpenClaw startup complete at $(date) ==="
"""

    def _username_from_email(self, email: str) -> str:
        """Extract and sanitize username from email address.

        This creates a username that matches what cloud providers use for SSH access.
        For example, "john.doe@example.com" becomes "john_doe".
        """
        # Extract the local part (before @)
        local_part = email.split("@")[0] if "@" in email else email
        # Replace dots and other common separators with underscores
        sanitized = local_part.replace(".", "_").replace("-", "_").replace("+", "_")
        # Remove any characters that aren't alphanumeric or underscore
        sanitized = "".join(c for c in sanitized if c.isalnum() or c == "_")
        # Ensure it doesn't start with a number
        if sanitized and sanitized[0].isdigit():
            sanitized = "u" + sanitized
        # Lowercase for consistency
        sanitized = sanitized.lower()
        # Default if empty
        return sanitized or "openclaw"

    def _get_bundle_download_script(self, bundle_url: str, decryption_key: str) -> str:
        """Generate script section to download and extract credential bundle.

        Args:
            bundle_url: Signed URL to download the bundle
            decryption_key: Base64-encoded decryption key

        Returns:
            Bash script section for bundle extraction
        """
        return f"""
# Download and decrypt startup bundle
echo "Downloading credential bundle..."
BUNDLE_URL="{bundle_url}"

# Download with error checking (show HTTP status code)
HTTP_CODE=$(curl -s -w "%{{http_code}}" -o /tmp/startup-bundle.enc "$BUNDLE_URL")
CURL_EXIT=$?

echo "curl exit code: $CURL_EXIT, HTTP status: $HTTP_CODE"

if [ $CURL_EXIT -ne 0 ]; then
    echo "ERROR: curl failed with exit code $CURL_EXIT"
    exit 1
fi

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: HTTP request failed with status $HTTP_CODE"
    echo "Response content (first 500 bytes):"
    head -c 500 /tmp/startup-bundle.enc
    exit 1
fi

if [ ! -f /tmp/startup-bundle.enc ]; then
    echo "ERROR: Bundle file was not created"
    exit 1
fi

BUNDLE_SIZE=$(stat -c%s /tmp/startup-bundle.enc 2>/dev/null || stat -f%z /tmp/startup-bundle.enc)
echo "Downloaded bundle size: $BUNDLE_SIZE bytes"

if [ "$BUNDLE_SIZE" -lt 50 ]; then
    echo "ERROR: Bundle file is too small ($BUNDLE_SIZE bytes), likely an error response"
    echo "Content:"
    cat /tmp/startup-bundle.enc
    exit 1
fi

echo "Decrypting and extracting bundle..."
python3 << 'DECRYPT_SCRIPT'
import base64
import json
import os
import sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Read encrypted data
with open('/tmp/startup-bundle.enc', 'rb') as f:
    encrypted_data = f.read()

print(f"Read {{len(encrypted_data)}} bytes of encrypted data")

# Validate minimum size (12 byte nonce + at least some ciphertext)
if len(encrypted_data) < 28:
    print(f"ERROR: Encrypted data too small ({{len(encrypted_data)}} bytes)")
    print(f"First 100 bytes (hex): {{encrypted_data[:100].hex()}}")
    print(f"First 100 bytes (text): {{encrypted_data[:100]}}")
    sys.exit(1)

# Decrypt
try:
    key = base64.b64decode("{decryption_key}")
    print(f"Decryption key length: {{len(key)}} bytes")
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    print(f"Nonce (hex): {{nonce.hex()}}")
    print(f"Ciphertext length: {{len(ciphertext)}} bytes")
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    print(f"Decryption successful, {{len(plaintext)}} bytes")
except Exception as e:
    print(f"ERROR: Decryption failed: {{e}}")
    print(f"First 50 bytes of encrypted data (hex): {{encrypted_data[:50].hex()}}")
    sys.exit(1)

# Parse bundle
bundle = json.loads(plaintext)

# Write config
os.makedirs(os.path.expanduser('~/.openclaw'), exist_ok=True)
with open(os.path.expanduser('~/.openclaw/openclaw.json'), 'w') as f:
    f.write(bundle['config_json'])
print('Written openclaw.json')

# Write env vars to .env file
env_lines = []
for name, value in bundle.get('env_vars', {{}}).items():
    # Escape for shell
    escaped = value.replace("'", "'\\\"'\\\"'")
    env_lines.append(f"export {{name}}='{{escaped}}'")

with open(os.path.expanduser('~/.openclaw/.env'), 'w') as f:
    f.write('\\n'.join(env_lines))
print(f'Written .env with {{len(env_lines)}} variables')

# Write channel credentials
for channel, creds_b64 in bundle.get('channel_credentials', {{}}).items():
    creds_dir = os.path.expanduser(f'~/.openclaw/credentials/{{channel}}/default')
    os.makedirs(creds_dir, exist_ok=True)
    creds_data = base64.b64decode(creds_b64)
    with open(os.path.join(creds_dir, 'creds.json'), 'wb') as f:
        f.write(creds_data)
    print(f'Written {{channel}} credentials')

print('Bundle extracted successfully')
DECRYPT_SCRIPT

DECRYPT_EXIT=$?
if [ $DECRYPT_EXIT -ne 0 ]; then
    echo "ERROR: Decryption script failed"
    exit 1
fi

# Clean up
rm -f /tmp/startup-bundle.enc

# Source env vars for current session
if [ -f ~/.openclaw/.env ]; then
    source ~/.openclaw/.env
fi

echo "Credential bundle processed successfully"
"""

    def get_health_check_command(self) -> str | None:
        """Check if OpenClaw setup is complete."""
        return "test -f ~/.openclaw/setup-complete"

    def get_default_gateway_port(self) -> int:
        """Get the default gateway port for OpenClaw."""
        return 18789
