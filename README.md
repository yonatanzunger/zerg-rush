# Zerg Rush

Secure Agent Fleet Management System - Deploy, manage, and monitor AI agents securely with complete isolation.

## Overview

Zerg Rush is a control panel for securely managing fleets of AI agents (starting with [openclaw](https://github.com/openclaw/openclaw)). Each agent runs in its own isolated VM with scoped credentials, ensuring that compromise of a single agent cannot spread to other resources.

## Features

- **Agent Isolation**: Each agent runs in a separate VM with no network access to other agents
- **Credential Management**: Securely store and selectively grant credentials to agents
- **Template System**: Save agent states as templates for quick deployment
- **Audit Logging**: Append-only log of all actions for compliance and debugging
- **Multi-Cloud Support**: Designed for GCP, with AWS and Azure planned

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (React)                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Backend API (FastAPI)                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Cloud Abstraction Layer                      │   │
│  │   VMProvider │ StorageProvider │ SecretProvider │ ...     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌─────────────┐
   │ Agent   │   │ Agent   │   │    Agent    │
   │  VM 1   │   │  VM 2   │   │    VM N     │
   └─────────┘   └─────────┘   └─────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- (For production) GCP account with:
  - Compute Engine API enabled
  - Cloud Storage API enabled
  - Secret Manager API enabled
  - OAuth 2.0 credentials configured

### Local Development

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/zerg-rush.git
   cd zerg-rush
   ```

2. Copy the environment file:
   ```bash
   cp backend/.env.example backend/.env
   # Edit backend/.env with your settings
   ```

3. Start the services:
   ```bash
   docker-compose up -d
   ```

4. Access the application:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API docs: http://localhost:8000/docs

### Manual Setup (without Docker)

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `SECRET_KEY` | JWT signing key | (required) |
| `CLOUD_PROVIDER` | Cloud provider (`gcp`, `aws`, `azure`) | `gcp` |
| `GCP_PROJECT_ID` | GCP project ID | (required for GCP) |
| `GOOGLE_CLIENT_ID` | OAuth client ID | (required) |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret | (required) |
| `FRONTEND_URL` | Frontend URL for CORS/redirects | `http://localhost:3000` |

## Project Structure

```
zerg-rush/
├── backend/
│   ├── app/
│   │   ├── api/          # API routes
│   │   ├── cloud/        # Cloud provider implementations
│   │   ├── models/       # SQLAlchemy models
│   │   ├── services/     # Business logic
│   │   └── db/           # Database configuration
│   ├── scripts/          # Setup scripts for agent platforms
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── pages/        # Page components
│   │   ├── services/     # API client
│   │   └── context/      # React context providers
│   └── public/
├── infrastructure/       # Terraform configurations
└── docker-compose.yml
```

## Security Model

1. **Agent Isolation**: Each agent VM is in an isolated network with no access to other agents
2. **No External Access**: Agent gateways are never exposed to the public internet
3. **Scoped Credentials**: Agents only receive explicitly granted credentials
4. **Audit Trail**: All actions are logged to an append-only audit log

## API Documentation

Once the backend is running, visit http://localhost:8000/docs for interactive API documentation.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
