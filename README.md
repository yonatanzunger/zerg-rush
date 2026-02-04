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
- (For production) Cloud account with appropriate APIs enabled:
  - **GCP**: Compute Engine, Cloud Run, Cloud Storage, Secret Manager APIs
  - **Azure**: Container Instances, Blob Storage, Key Vault
- OAuth 2.0 app credentials configured in your cloud provider
- Users must have appropriate IAM/RBAC roles (see [User Cloud Requirements](#user-cloud-requirements))

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

### Using the Start Script (Windows)

The easiest way to start the backend server locally:

```powershell
.\scripts\start-server.ps1
```

This script automatically:
- Starts a PostgreSQL Docker container (`zergrush-db`) if Docker is available
- Waits for PostgreSQL to be ready and creates the database if needed
- Creates a Python virtual environment if needed
- Installs dependencies
- Copies `.env.example` to `.env` if no `.env` exists
- Starts the server with auto-reload enabled

**Prerequisites:**
- Docker Desktop (for automatic PostgreSQL management)
- Python 3.x

**Options:**
```powershell
.\scripts\start-server.ps1 -Port 8080           # Use a different port
.\scripts\start-server.ps1 -Hostname 0.0.0.0    # Bind to all interfaces
.\scripts\start-server.ps1 -NoReload            # Disable auto-reload
```

> **Note:** If Docker is not available, you'll need to run PostgreSQL manually on `localhost:5432` with a database named `zergrush`.

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
| `GCP_REGION` | GCP region for resources | `us-central1` |
| `GCP_ZONE` | GCP zone for VMs | `us-central1-a` |
| `GCP_COMPUTE_TYPE` | Compute type (`gce` or `cloudrun`) | `cloudrun` |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Service account for URL signing | (optional, see Cloud Setup) |
| `GOOGLE_CLIENT_ID` | OAuth client ID | (required) |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret | (required) |
| `OAUTH_REDIRECT_URI` | OAuth callback URL | `http://localhost:8000/auth/callback` |
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

## Cloud Setup

Zerg Rush supports two authentication modes for GCP. Choose the one that fits your needs.

### GCP Setup

#### 1. Create a GCP Project

If you don't have one already, create a GCP project:

```bash
gcloud projects create YOUR_PROJECT_ID --name="Zerg Rush"
gcloud config set project YOUR_PROJECT_ID
```

#### 2. Enable Required APIs

```bash
gcloud services enable \
  compute.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com
```

#### 3. Create OAuth 2.0 Credentials (for user login)

1. Go to the [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials** → **OAuth client ID**
3. Configure the consent screen if prompted:
   - User Type: **Internal** (for organization) or **External** (for testing)
   - Add scopes: `openid`, `email`, `profile`, and `https://www.googleapis.com/auth/cloud-platform`
4. Create OAuth client:
   - Application type: **Web application**
   - Name: `Zerg Rush`
   - Authorized redirect URIs: `http://localhost:8000/auth/callback` (add production URLs as needed)
5. Save the **Client ID** and **Client Secret**

#### 4. Choose Authentication Mode

Zerg Rush needs to sign URLs for secure credential delivery to VMs. There are two ways to enable this:

---

**Option A: Service Account Key (Simpler Setup)**

Run Zerg Rush with a service account that has a key file. This is simpler but means cloud operations are performed as the service account, not individual users.

```bash
PROJECT_ID=$(gcloud config get-value project)

# Create a service account for Zerg Rush
gcloud iam service-accounts create zerg-rush \
  --display-name="Zerg Rush Service Account"

SERVICE_ACCOUNT="zerg-rush@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant required permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/compute.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/iam.serviceAccountUser"

# Create and download a key file
gcloud iam service-accounts keys create ~/zerg-rush-key.json \
  --iam-account=$SERVICE_ACCOUNT

# Set the environment variable (add to your shell profile)
export GOOGLE_APPLICATION_CREDENTIALS=~/zerg-rush-key.json
```

With this setup, you do **not** need to set `GCP_SERVICE_ACCOUNT_EMAIL`.

---

**Option B: User OAuth Credentials with Signing Delegation (Better Audit Trail)**

Cloud operations are performed using each user's OAuth credentials, providing better audit trails. This requires a separate service account for URL signing.

**Create the signing service account:**

```bash
PROJECT_ID=$(gcloud config get-value project)

# Create a service account just for signing URLs
gcloud iam service-accounts create zerg-rush-signer \
  --display-name="Zerg Rush URL Signer"

SIGNER_SA="zerg-rush-signer@${PROJECT_ID}.iam.gserviceaccount.com"

# Allow the signer to read storage objects (required for signed URLs)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SIGNER_SA}" \
  --role="roles/storage.objectViewer"
```

**Grant users permission to use the signing service account:**

For each user who will use Zerg Rush:

```bash
USER_EMAIL="user@example.com"

# Allow user to sign blobs using the service account
gcloud iam service-accounts add-iam-policy-binding $SIGNER_SA \
  --member="user:${USER_EMAIL}" \
  --role="roles/iam.serviceAccountTokenCreator"
```

**Grant users permission to manage cloud resources:**

```bash
USER_EMAIL="user@example.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:${USER_EMAIL}" \
  --role="roles/compute.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:${USER_EMAIL}" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:${USER_EMAIL}" \
  --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:${USER_EMAIL}" \
  --role="roles/iam.serviceAccountUser"
```

Set `GCP_SERVICE_ACCOUNT_EMAIL` in your `.env` to the signer service account email.

---

#### 5. Configure Environment Variables

Add these to your `backend/.env` file:

```bash
# Cloud provider
CLOUD_PROVIDER=gcp

# GCP settings
GCP_PROJECT_ID=your-project-id
GCP_REGION=us-central1
GCP_ZONE=us-central1-a
GCP_COMPUTE_TYPE=gce

# Service account for URL signing (Option B only - omit for Option A)
GCP_SERVICE_ACCOUNT_EMAIL=zerg-rush-signer@your-project-id.iam.gserviceaccount.com

# OAuth credentials (from step 3)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
OAUTH_REDIRECT_URI=http://localhost:8000/auth/callback
```

#### Summary: Required Permissions by Mode

**Option A (Service Account Key):**

| Role | Granted To |
|------|------------|
| `roles/compute.admin` | Service account |
| `roles/storage.admin` | Service account |
| `roles/secretmanager.admin` | Service account |
| `roles/iam.serviceAccountUser` | Service account |

**Option B (User OAuth):**

| Role | Granted To |
|------|------------|
| `roles/compute.admin` | Each user |
| `roles/storage.admin` | Each user |
| `roles/secretmanager.admin` | Each user |
| `roles/iam.serviceAccountUser` | Each user |
| `roles/storage.objectViewer` | Signer service account |
| `roles/iam.serviceAccountTokenCreator` | Each user (on signer SA) |

### Azure Setup

#### Required RBAC Roles

You need these RBAC roles in your resource group:
- `Contributor` - Create/manage resources
- `Key Vault Secrets Officer` - Manage secrets
- `Storage Blob Data Contributor` - Manage blob storage

See [.clarity-protocol/solution/user-perspective.md](.clarity-protocol/solution/user-perspective.md) for detailed setup instructions.

## Security Model

1. **Agent Isolation**: Each agent VM is in an isolated network with no access to other agents
2. **No External Access**: Agent gateways are never exposed to the public internet
3. **Scoped Credentials**: Agents only receive explicitly granted credentials
4. **User Credentials**: All cloud operations use OAuth credentials from user login, not application-level credentials
5. **Token Encryption**: OAuth tokens are encrypted at rest using Fernet symmetric encryption
6. **Audit Trail**: All actions are logged to an append-only audit log

## API Documentation

Once the backend is running, visit http://localhost:8000/docs for interactive API documentation.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
