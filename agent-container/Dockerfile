# Agent container for Cloud Run
# This container runs openclaw and exposes the gateway on port 8080

FROM node:22-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install pnpm
RUN npm install -g pnpm

# Create non-root user
RUN useradd -m -s /bin/bash agent
USER agent
WORKDIR /home/agent

# Install openclaw
RUN pnpm add -g openclaw@latest

# Create config directory
RUN mkdir -p /home/agent/.openclaw

# Copy startup script
COPY --chown=agent:agent entrypoint.sh /home/agent/entrypoint.sh
RUN chmod +x /home/agent/entrypoint.sh

# Cloud Run requires port 8080
ENV PORT=8080
ENV GATEWAY_PORT=8080

EXPOSE 8080

ENTRYPOINT ["/home/agent/entrypoint.sh"]
