#!/bin/bash
set -e

# Configure openclaw from environment variables
CONFIG_FILE="/home/agent/.openclaw/openclaw.json"

# Create config with environment-provided settings
cat > "$CONFIG_FILE" << EOF
{
  "agent": {
    "model": "${AGENT_MODEL:-anthropic/claude-sonnet-4-20250514}"
  },
  "gateway": {
    "port": ${GATEWAY_PORT:-8080},
    "host": "0.0.0.0"
  }
}
EOF

# If LLM credentials are provided, add them to config
if [ -n "$ANTHROPIC_API_KEY" ]; then
    # Update config with API key
    echo "Anthropic API key configured"
fi

echo "Starting openclaw gateway on port ${GATEWAY_PORT:-8080}..."
echo "Agent ID: ${AGENT_ID:-unknown}"
echo "User ID: ${USER_ID:-unknown}"

# Start the gateway
exec openclaw gateway --port ${GATEWAY_PORT:-8080} --verbose
