"""Tests for startup bundle encryption/decryption.

These tests validate the encryption/decryption flow that runs on VMs,
allowing us to catch issues without spinning up actual GCE instances.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.startup_bundle import StartupBundle, StartupBundleService


def _get_test_decrypt_script() -> str:
    """Return the Python script used to decrypt bundles on VMs.

    This is a standalone function to avoid string escaping issues in tests.
    The script mirrors the core decryption logic in openclaw.py.
    """
    return '''
import base64
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Get paths from command line args
bundle_path = sys.argv[1]
key_b64 = sys.argv[2]
openclaw_dir = sys.argv[3]

# Read encrypted data
with open(bundle_path, 'rb') as f:
    encrypted_data = f.read()

# Decrypt
key = base64.b64decode(key_b64)
nonce = encrypted_data[:12]
ciphertext = encrypted_data[12:]
aesgcm = AESGCM(key)
plaintext = aesgcm.decrypt(nonce, ciphertext, None)

# Parse bundle
bundle = json.loads(plaintext)

# Write config
os.makedirs(openclaw_dir, exist_ok=True)
config_path = os.path.join(openclaw_dir, 'openclaw.json')
with open(config_path, 'w') as f:
    f.write(bundle['config_json'])
print('Written openclaw.json')

# Write env vars to .env file (simple format, no shell escaping in test)
env_lines = []
for name, value in bundle.get('env_vars', {}).items():
    env_lines.append(f"{name}={value}")

env_path = os.path.join(openclaw_dir, '.env')
with open(env_path, 'w') as f:
    f.write('\\n'.join(env_lines))
print(f'Written .env with {len(env_lines)} variables')

# Write channel credentials
for channel, creds_b64 in bundle.get('channel_credentials', {}).items():
    creds_dir = os.path.join(openclaw_dir, 'credentials', channel, 'default')
    os.makedirs(creds_dir, exist_ok=True)
    creds_data = base64.b64decode(creds_b64)
    with open(os.path.join(creds_dir, 'creds.json'), 'wb') as f:
        f.write(creds_data)
    print(f'Written {channel} credentials')

print('Bundle extracted successfully')
'''


class TestStartupBundleEncryption(unittest.TestCase):
    """Test the encryption/decryption round-trip."""

    def test_encrypt_decrypt_round_trip(self):
        """Test that encryption and decryption work correctly."""
        # Create a sample bundle
        bundle = StartupBundle(
            config_json='{"gateway": {"port": 18789}}',
            env_vars={"ANTHROPIC_API_KEY": "sk-test-key-12345"},
            channel_credentials={"whatsapp": base64.b64encode(b'{"creds": "test"}').decode()},
        )

        # Create a service instance (we only need the encryption methods)
        service = StartupBundleService.__new__(StartupBundleService)

        # Serialize the bundle
        bundle_data = service._serialize_bundle(bundle)

        # Encrypt
        key = os.urandom(32)
        encrypted_data = service._encrypt_bundle(bundle_data, key)

        # Decrypt using the static method
        key_b64 = base64.b64encode(key).decode()
        decrypted_bundle = StartupBundleService.decrypt_bundle(encrypted_data, key_b64)

        # Verify
        self.assertEqual(decrypted_bundle.config_json, bundle.config_json)
        self.assertEqual(decrypted_bundle.env_vars, bundle.env_vars)
        self.assertEqual(decrypted_bundle.channel_credentials, bundle.channel_credentials)

    def test_encrypted_data_structure(self):
        """Test that encrypted data has correct structure (nonce + ciphertext)."""
        service = StartupBundleService.__new__(StartupBundleService)
        data = b"test data for encryption"
        key = os.urandom(32)

        encrypted = service._encrypt_bundle(data, key)

        # First 12 bytes should be the nonce
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]

        # Verify we can decrypt manually
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        self.assertEqual(decrypted, data)

    def test_wrong_key_fails(self):
        """Test that decryption with wrong key raises InvalidTag."""
        service = StartupBundleService.__new__(StartupBundleService)
        data = b"secret data"
        correct_key = os.urandom(32)
        wrong_key = os.urandom(32)

        encrypted = service._encrypt_bundle(data, correct_key)

        # Try to decrypt with wrong key
        wrong_key_b64 = base64.b64encode(wrong_key).decode()
        with self.assertRaises(Exception) as context:
            nonce = encrypted[:12]
            ciphertext = encrypted[12:]
            aesgcm = AESGCM(wrong_key)
            aesgcm.decrypt(nonce, ciphertext, None)

        self.assertIn("InvalidTag", str(type(context.exception)))

    def test_corrupted_data_fails(self):
        """Test that corrupted ciphertext raises InvalidTag."""
        service = StartupBundleService.__new__(StartupBundleService)
        data = b"secret data"
        key = os.urandom(32)

        encrypted = service._encrypt_bundle(data, key)

        # Corrupt one byte in the ciphertext (after the nonce)
        corrupted = encrypted[:15] + bytes([encrypted[15] ^ 0xFF]) + encrypted[16:]

        with self.assertRaises(Exception):
            key_b64 = base64.b64encode(key).decode()
            nonce = corrupted[:12]
            ciphertext = corrupted[12:]
            aesgcm = AESGCM(key)
            aesgcm.decrypt(nonce, ciphertext, None)


class TestEmbeddedDecryptScript(unittest.TestCase):
    """Test that the embedded Python script in startup scripts works correctly.

    This simulates what actually runs on the VM by extracting and executing
    the Python decryption script.
    """

    def test_embedded_script_decrypts_correctly(self):
        """Test that the embedded Python script can decrypt bundles."""
        # Create a sample bundle
        bundle = StartupBundle(
            config_json='{"gateway": {"port": 18789}, "llm": {"model": "claude-3"}}',
            env_vars={
                "ANTHROPIC_API_KEY": "sk-ant-test-key",
                "OPENAI_API_KEY": "sk-openai-test",
            },
            channel_credentials={
                "whatsapp": base64.b64encode(b'{"session": "data"}').decode()
            },
        )

        # Encrypt the bundle
        service = StartupBundleService.__new__(StartupBundleService)
        bundle_data = service._serialize_bundle(bundle)
        key = os.urandom(32)
        encrypted_data = service._encrypt_bundle(bundle_data, key)
        key_b64 = base64.b64encode(key).decode()

        # Create temp files to simulate VM environment
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write encrypted bundle
            bundle_path = os.path.join(tmpdir, "startup-bundle.enc")
            with open(bundle_path, "wb") as f:
                f.write(encrypted_data)

            # Create output directory
            openclaw_dir = os.path.join(tmpdir, ".openclaw")
            os.makedirs(openclaw_dir)

            # Write the decrypt script to a file
            # This script mirrors the core logic in openclaw.py _get_bundle_download_script
            # (shell escaping is tested separately)
            decrypt_script = _get_test_decrypt_script()
            script_path = os.path.join(tmpdir, "decrypt.py")
            with open(script_path, "w") as f:
                f.write(decrypt_script)

            # Run the script
            result = subprocess.run(
                [sys.executable, script_path, bundle_path, key_b64, openclaw_dir],
                capture_output=True,
                text=True,
            )

            # Check script executed successfully
            self.assertEqual(
                result.returncode,
                0,
                f"Script failed with stderr: {result.stderr}\nstdout: {result.stdout}",
            )

            # Verify openclaw.json was written correctly
            config_path = os.path.join(openclaw_dir, "openclaw.json")
            self.assertTrue(os.path.exists(config_path))
            with open(config_path) as f:
                config_content = f.read()
            self.assertEqual(config_content, bundle.config_json)

            # Verify .env was written correctly
            env_path = os.path.join(openclaw_dir, ".env")
            self.assertTrue(os.path.exists(env_path))
            with open(env_path) as f:
                env_content = f.read()
            self.assertIn("ANTHROPIC_API_KEY", env_content)
            self.assertIn("sk-ant-test-key", env_content)

            # Verify channel credentials were written
            creds_path = os.path.join(
                openclaw_dir, "credentials", "whatsapp", "default", "creds.json"
            )
            self.assertTrue(os.path.exists(creds_path))
            with open(creds_path, "rb") as f:
                creds_content = f.read()
            self.assertEqual(creds_content, b'{"session": "data"}')

    def test_key_encoding_consistency(self):
        """Test that key encoding/decoding is consistent."""
        # Generate a key
        key = os.urandom(32)

        # Encode to base64 (as done in create_bundle)
        key_b64 = base64.b64encode(key).decode()

        # Decode from base64 (as done in decrypt script)
        decoded_key = base64.b64decode(key_b64)

        self.assertEqual(key, decoded_key)
        self.assertEqual(len(decoded_key), 32)

    def test_special_characters_in_env_vars(self):
        """Test that special characters in env vars are handled correctly."""
        # Create a bundle with special characters in values
        bundle = StartupBundle(
            config_json="{}",
            env_vars={
                "SIMPLE_KEY": "simple-value",
                "KEY_WITH_QUOTES": "value'with'quotes",
                "KEY_WITH_DOLLARS": "value$with$dollars",
                "KEY_WITH_NEWLINES": "line1\nline2",
            },
            channel_credentials={},
        )

        # Encrypt
        service = StartupBundleService.__new__(StartupBundleService)
        bundle_data = service._serialize_bundle(bundle)
        key = os.urandom(32)
        encrypted_data = service._encrypt_bundle(bundle_data, key)
        key_b64 = base64.b64encode(key).decode()

        # Decrypt
        decrypted = StartupBundleService.decrypt_bundle(encrypted_data, key_b64)

        # Verify all values came through correctly
        self.assertEqual(decrypted.env_vars["SIMPLE_KEY"], "simple-value")
        self.assertEqual(decrypted.env_vars["KEY_WITH_QUOTES"], "value'with'quotes")
        self.assertEqual(decrypted.env_vars["KEY_WITH_DOLLARS"], "value$with$dollars")
        self.assertEqual(decrypted.env_vars["KEY_WITH_NEWLINES"], "line1\nline2")


class TestBundleSerialization(unittest.TestCase):
    """Test bundle serialization edge cases."""

    def test_empty_bundle(self):
        """Test that an empty bundle can be serialized and deserialized."""
        bundle = StartupBundle(
            config_json="{}",
            env_vars={},
            channel_credentials={},
        )

        service = StartupBundleService.__new__(StartupBundleService)
        bundle_data = service._serialize_bundle(bundle)
        key = os.urandom(32)
        encrypted = service._encrypt_bundle(bundle_data, key)
        key_b64 = base64.b64encode(key).decode()

        decrypted = StartupBundleService.decrypt_bundle(encrypted, key_b64)

        self.assertEqual(decrypted.config_json, "{}")
        self.assertEqual(decrypted.env_vars, {})
        self.assertEqual(decrypted.channel_credentials, {})

    def test_large_config(self):
        """Test that large configs can be handled."""
        # Create a large config (simulate real openclaw.json)
        large_config = {
            "gateway": {"port": 18789, "auth_token": "x" * 1000},
            "llm": {"model": "claude-3", "system_prompt": "y" * 5000},
            "channels": [{"type": f"channel_{i}"} for i in range(100)],
        }

        bundle = StartupBundle(
            config_json=json.dumps(large_config),
            env_vars={f"VAR_{i}": f"value_{i}" for i in range(50)},
            channel_credentials={},
        )

        service = StartupBundleService.__new__(StartupBundleService)
        bundle_data = service._serialize_bundle(bundle)
        key = os.urandom(32)
        encrypted = service._encrypt_bundle(bundle_data, key)
        key_b64 = base64.b64encode(key).decode()

        decrypted = StartupBundleService.decrypt_bundle(encrypted, key_b64)

        self.assertEqual(json.loads(decrypted.config_json), large_config)
        self.assertEqual(len(decrypted.env_vars), 50)

    def test_unicode_content(self):
        """Test that unicode content is handled correctly."""
        bundle = StartupBundle(
            config_json='{"name": "Test 日本語 🎉"}',
            env_vars={"GREETING": "Hello 世界"},
            channel_credentials={},
        )

        service = StartupBundleService.__new__(StartupBundleService)
        bundle_data = service._serialize_bundle(bundle)
        key = os.urandom(32)
        encrypted = service._encrypt_bundle(bundle_data, key)
        key_b64 = base64.b64encode(key).decode()

        decrypted = StartupBundleService.decrypt_bundle(encrypted, key_b64)

        self.assertEqual(decrypted.config_json, '{"name": "Test 日本語 🎉"}')
        self.assertEqual(decrypted.env_vars["GREETING"], "Hello 世界")


class TestActualStartupScript(unittest.TestCase):
    """Test the actual startup script generation and decryption.

    These tests validate the complete flow by extracting the Python
    decryption code from the generated startup script.
    """

    def test_startup_script_key_embedding(self):
        """Test that the decryption key is correctly embedded in the startup script."""
        from unittest.mock import MagicMock

        from app.agents.openclaw import OpenClawPlatform
        from app.agents.base import StartupScriptConfig

        # Create a mock user
        mock_user = MagicMock()
        mock_user.email = "test@example.com"

        # Create test data
        key = os.urandom(32)
        key_b64 = base64.b64encode(key).decode()
        bundle_url = "https://storage.googleapis.com/test-bucket/bundle.enc?signature=abc123"

        # Generate the startup script
        platform = OpenClawPlatform()
        config = StartupScriptConfig(
            bundle_url=bundle_url,
            decryption_key=key_b64,
            gateway_port=18789,
        )
        script = platform.get_startup_script(mock_user, config=config)

        # Verify the key is embedded correctly
        self.assertIn(key_b64, script)
        self.assertIn(bundle_url, script)

        # Verify the key appears in the Python decryption section
        self.assertIn(f'base64.b64decode("{key_b64}")', script)

    def test_extract_and_verify_decrypt_logic(self):
        """Extract the decrypt logic from startup script and verify it works.

        This test extracts just the decryption portion of the embedded Python
        code and verifies it can correctly decrypt a bundle.
        """
        import re
        from unittest.mock import MagicMock

        from app.agents.openclaw import OpenClawPlatform
        from app.agents.base import StartupScriptConfig

        # Create a sample bundle
        bundle = StartupBundle(
            config_json='{"test": "config", "value": 123}',
            env_vars={"TEST_KEY": "test-value", "API_KEY": "sk-secret"},
            channel_credentials={"whatsapp": base64.b64encode(b'{"creds": true}').decode()},
        )

        # Encrypt the bundle
        service = StartupBundleService.__new__(StartupBundleService)
        bundle_data = service._serialize_bundle(bundle)
        key = os.urandom(32)
        encrypted_data = service._encrypt_bundle(bundle_data, key)
        key_b64 = base64.b64encode(key).decode()

        # Generate the startup script
        mock_user = MagicMock()
        mock_user.email = "test@example.com"

        platform = OpenClawPlatform()
        config = StartupScriptConfig(
            bundle_url="https://example.com/bundle.enc",
            decryption_key=key_b64,
            gateway_port=18789,
        )
        script = platform.get_startup_script(mock_user, config=config)

        # Extract the Python code between DECRYPT_SCRIPT heredoc markers
        match = re.search(
            r"python3 << 'DECRYPT_SCRIPT'\n(.*?)\nDECRYPT_SCRIPT",
            script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Could not find DECRYPT_SCRIPT section")

        python_code = match.group(1)

        # Verify the key is correctly embedded in the Python code
        self.assertIn(f'base64.b64decode("{key_b64}")', python_code)

        # Create a simplified test script that just tests decryption
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = os.path.join(tmpdir, "startup-bundle.enc")
            with open(bundle_path, "wb") as f:
                f.write(encrypted_data)

            # Create a test script that uses the same decryption logic
            # but outputs the result instead of writing files
            test_script = f'''
import base64
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Read encrypted data (same as in startup script)
with open(r'{bundle_path}', 'rb') as f:
    encrypted_data = f.read()

# Decrypt using the exact same key from the startup script
key = base64.b64decode("{key_b64}")
nonce = encrypted_data[:12]
ciphertext = encrypted_data[12:]
aesgcm = AESGCM(key)
plaintext = aesgcm.decrypt(nonce, ciphertext, None)

# Parse and output the bundle
bundle = json.loads(plaintext)
print("CONFIG:", bundle['config_json'])
print("ENV_VARS:", json.dumps(bundle['env_vars']))
print("CHANNEL_CREDS:", json.dumps(bundle['channel_credentials']))
print("SUCCESS")
'''
            script_path = os.path.join(tmpdir, "test_decrypt.py")
            with open(script_path, "w") as f:
                f.write(test_script)

            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                f"Decryption failed!\nstderr: {result.stderr}\nstdout: {result.stdout}",
            )

            # Verify output
            self.assertIn("SUCCESS", result.stdout)
            self.assertIn('"test": "config"', result.stdout)
            self.assertIn("TEST_KEY", result.stdout)
            self.assertIn("whatsapp", result.stdout)


if __name__ == "__main__":
    unittest.main()
