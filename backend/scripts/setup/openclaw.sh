#!/bin/bash
# Setup script for openclaw agents
# This script is run on the VM after initial creation

set -e

echo "=== Zerg Rush Agent Setup: openclaw ==="

# Update system
echo "Updating system packages..."
apt-get update
apt-get upgrade -y

# Install dependencies
echo "Installing dependencies..."
apt-get install -y curl git build-essential

# Install Node.js 22
echo "Installing Node.js 22..."
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# Verify Node.js installation
echo "Node.js version: $(node --version)"
echo "npm version: $(npm --version)"

# Install pnpm
echo "Installing pnpm..."
npm install -g pnpm

# Create openclaw user
echo "Creating openclaw user..."
useradd -m -s /bin/bash openclaw || true

# Install openclaw as the openclaw user
echo "Installing openclaw..."
sudo -u openclaw bash << 'EOF'
cd ~
pnpm add -g openclaw@latest

# Create config directory
mkdir -p ~/.openclaw

# Create minimal config
cat > ~/.openclaw/openclaw.json << 'CONFIG'
{
  "agent": {
    "model": "anthropic/claude-sonnet-4-20250514"
  },
  "gateway": {
    "port": 18789,
    "host": "0.0.0.0"
  }
}
CONFIG
EOF

# Create systemd service for openclaw gateway
echo "Creating systemd service..."
cat > /etc/systemd/system/openclaw-gateway.service << 'SERVICE'
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/home/openclaw
ExecStart=/usr/bin/env openclaw gateway --port 18789 --verbose
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

# Enable and start the service
systemctl daemon-reload
systemctl enable openclaw-gateway

# Signal setup complete
touch /home/openclaw/.openclaw/setup-complete

echo "=== Setup complete ==="
echo "OpenClaw gateway will start on boot at port 18789"
