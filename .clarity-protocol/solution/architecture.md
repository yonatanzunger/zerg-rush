# Zerg Rush - Technical Architecture

## Overview

Zerg Rush is a secure agent fleet management system built with a cloud-agnostic architecture. The system allows users to deploy, manage, and interact with AI agents (starting with openclaw) running in isolated VMs.

---

## Architecture Principles

1. **Agent Isolation**: Each agent runs in its own VM with minimal, scoped credentials
2. **Cloud Abstraction**: Core logic is cloud-independent; cloud-specific implementations are pluggable
3. **Security by Default**: Credentials are never exposed to agents beyond what's explicitly granted
4. **Audit Everything**: All actions are logged to an append-only audit log

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Frontend (React SPA)                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Landing  │ │Dashboard │ │ Agent    │ │ Saved    │ │ Audit    │          │
│  │   Page   │ │          │ │ Detail   │ │ Agents   │ │ Logs     │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTPS
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Backend API (Python/FastAPI)                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        API Layer (REST)                              │    │
│  │  /auth  /agents  /saved-agents  /credentials  /logs  /users         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      Service Layer                                   │    │
│  │  AgentService  CredentialService  AuditService  TemplateService     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                   Cloud Abstraction Layer                            │    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │    │
│  │  │ VMProvider  │ │StorageProvi-│ │SecretProvi- │ │  Identity   │    │    │
│  │  │  Interface  │ │der Interface│ │der Interface│ │  Provider   │    │    │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘    │    │
│  │         │               │               │               │           │    │
│  │    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐       │    │
│  │    │GCP│AWS│…│    │GCS│S3 │…│    │GSM│ASM│…│    │GCP│AWS│…│       │    │
│  │    └─────────┘    └─────────┘    └─────────┘    └─────────┘       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   PostgreSQL    │  │  Secret Store   │  │  Object Storage │
│   (Cloud SQL/   │  │ (Secret Manager/│  │   (GCS/S3/     │
│    RDS/Azure)   │  │  Secrets Mgr)   │  │  Azure Blob)    │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Agent VM 1    │  │   Agent VM 2    │  │   Agent VM N    │
│  ┌───────────┐  │  │  ┌───────────┐  │  │  ┌───────────┐  │
│  │ openclaw  │  │  │  │ openclaw  │  │  │  │ openclaw  │  │
│  │  gateway  │  │  │  │  gateway  │  │  │  │  gateway  │  │
│  │ :18789    │  │  │  │ :18789    │  │  │  │ :18789    │  │
│  └───────────┘  │  │  └───────────┘  │  │  └───────────┘  │
│  ┌───────────┐  │  │  ┌───────────┐  │  │  ┌───────────┐  │
│  │  Scoped   │  │  │  │  Scoped   │  │  │  │  Scoped   │  │
│  │Credentials│  │  │  │Credentials│  │  │  │Credentials│  │
│  └───────────┘  │  │  └───────────┘  │  │  └───────────┘  │
│  Bucket: agent-1│  │  Bucket: agent-2│  │  Bucket: agent-n│
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Cloud Abstraction Layer

The cloud abstraction layer defines interfaces that are implemented per cloud provider.

### Interfaces

```python
# cloud/interfaces.py

class VMProvider(ABC):
    """Manages VM lifecycle"""
    @abstractmethod
    async def create_vm(self, config: VMConfig) -> VMInstance: ...
    @abstractmethod
    async def delete_vm(self, vm_id: str) -> None: ...
    @abstractmethod
    async def start_vm(self, vm_id: str) -> None: ...
    @abstractmethod
    async def stop_vm(self, vm_id: str) -> None: ...
    @abstractmethod
    async def get_vm_status(self, vm_id: str) -> VMStatus: ...
    @abstractmethod
    async def run_command(self, vm_id: str, command: str) -> CommandResult: ...
    @abstractmethod
    async def upload_file(self, vm_id: str, local_path: str, remote_path: str) -> None: ...
    @abstractmethod
    async def download_file(self, vm_id: str, remote_path: str, local_path: str) -> None: ...

class StorageProvider(ABC):
    """Manages object storage for data exchange"""
    @abstractmethod
    async def create_bucket(self, name: str, user_id: str) -> str: ...
    @abstractmethod
    async def delete_bucket(self, bucket_id: str) -> None: ...
    @abstractmethod
    async def create_scoped_credentials(self, bucket_id: str) -> ScopedCredentials: ...
    @abstractmethod
    async def list_objects(self, bucket_id: str, prefix: str = "") -> List[StorageObject]: ...
    @abstractmethod
    async def upload_object(self, bucket_id: str, key: str, data: bytes) -> None: ...
    @abstractmethod
    async def download_object(self, bucket_id: str, key: str) -> bytes: ...

class SecretProvider(ABC):
    """Manages secrets/credentials storage"""
    @abstractmethod
    async def store_secret(self, user_id: str, name: str, value: str) -> str: ...
    @abstractmethod
    async def get_secret(self, secret_id: str) -> str: ...
    @abstractmethod
    async def delete_secret(self, secret_id: str) -> None: ...
    @abstractmethod
    async def list_secrets(self, user_id: str) -> List[SecretMetadata]: ...

class IdentityProvider(ABC):
    """Handles OAuth authentication"""
    @abstractmethod
    async def verify_token(self, token: str) -> UserInfo: ...
    @abstractmethod
    async def get_auth_url(self, redirect_uri: str) -> str: ...
    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse: ...
```

### Cloud Implementations

| Interface        | GCP                  | AWS             | Azure                       |
| ---------------- | -------------------- | --------------- | --------------------------- |
| VMProvider       | Compute Engine       | EC2             | Azure VMs                   |
| StorageProvider  | Cloud Storage        | S3              | Blob Storage                |
| SecretProvider   | Secret Manager       | Secrets Manager | Key Vault                   |
| IdentityProvider | Google Identity      | Cognito         | Azure AD                    |
| Database         | Cloud SQL (Postgres) | RDS (Postgres)  | Azure Database for Postgres |

---

## Data Model

### Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│      User       │       │   ActiveAgent   │       │   SavedAgent    │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │──┐    │ id (PK)         │       │ id (PK)         │
│ email           │  │    │ user_id (FK)    │──┐    │ user_id (FK)    │──┐
│ name            │  │    │ name            │  │    │ name            │  │
│ oauth_provider  │  │    │ vm_id           │  │    │ setup_script_id │  │
│ oauth_subject   │  │    │ vm_size         │  │    │ is_starred      │  │
│ created_at      │  │    │ vm_status       │  │    │ config_snapshot │  │
│ last_login      │  │    │ vm_internal_ip  │  │    │ created_at      │  │
└─────────────────┘  │    │ bucket_id       │  │    │ source_agent_id │  │
                     │    │ current_task    │  │    └─────────────────┘  │
                     │    │ platform_type   │  │             │           │
                     │    │ template_id(FK) │──┼─────────────┘           │
                     │    └─────────────────┘  │                         │
                     │             │           │                         │
                     │             ▼           │                         │
                     │    ┌─────────────────┐  │                         │
                     │    │AgentCredential  │  │                         │
                     │    ├─────────────────┤  │                         │
                     │    │ agent_id (FK)   │──┘                         │
                     │    │ credential_id   │──────┐                     │
                     │    │ granted_at      │      │                     │
                     │    └─────────────────┘      │                     │
                     │                             │                     │
                     │    ┌─────────────────┐      │                     │
                     └───▶│   Credential    │◀─────┘                     │
                          ├─────────────────┤                            │
                          │ id (PK)         │                            │
                          │ user_id (FK)    │◀───────────────────────────┘
                          │ name            │
                          │ type            │  (llm, cloud, utility)
                          │ secret_ref      │  (reference to keyvault)
                          │ created_at      │
                          └─────────────────┘

┌─────────────────┐       ┌─────────────────┐
│   SetupScript   │       │    AuditLog     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ platform_type   │       │ user_id (FK)    │
│ platform_version│       │ action_type     │
│ script_content  │       │ target_type     │
│ is_system       │       │ target_id       │
│ created_at      │       │ details (JSON)  │
└─────────────────┘       │ timestamp       │
                          │ ip_address      │
                          └─────────────────┘
```

### Key Tables

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    oauth_provider VARCHAR(50) NOT NULL,  -- 'google', 'microsoft', etc.
    oauth_subject VARCHAR(255) NOT NULL,   -- Provider's user ID
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE,
    UNIQUE(oauth_provider, oauth_subject)
);

-- Active agents
CREATE TABLE active_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    vm_id VARCHAR(255) NOT NULL,           -- Cloud provider's VM ID
    vm_size VARCHAR(50) NOT NULL,          -- e.g., 'e2-small', 't3.small'
    vm_status VARCHAR(50) NOT NULL,        -- 'running', 'stopped', 'starting', etc.
    vm_internal_ip VARCHAR(45),            -- Internal IP for backend→agent communication
    bucket_id VARCHAR(255) NOT NULL,       -- Data exchange bucket
    current_task TEXT,
    platform_type VARCHAR(50) NOT NULL,    -- 'openclaw', etc.
    platform_version VARCHAR(50),
    template_id UUID REFERENCES saved_agents(id),
    gateway_port INTEGER DEFAULT 18789,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Saved agents (templates/snapshots)
CREATE TABLE saved_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    platform_type VARCHAR(50) NOT NULL,
    setup_script_id UUID REFERENCES setup_scripts(id),
    config_snapshot JSONB,                 -- Serialized config files
    is_starred BOOLEAN DEFAULT FALSE,
    source_agent_id UUID,                  -- Agent this was saved from
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Credentials (metadata only; actual secrets in keyvault)
CREATE TABLE credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,             -- 'llm', 'cloud', 'utility'
    description TEXT,
    secret_ref VARCHAR(255) NOT NULL,      -- Keyvault reference
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Junction table: which credentials an agent has
CREATE TABLE agent_credentials (
    agent_id UUID NOT NULL REFERENCES active_agents(id) ON DELETE CASCADE,
    credential_id UUID NOT NULL REFERENCES credentials(id),
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (agent_id, credential_id)
);

-- Setup scripts for different agent platforms
CREATE TABLE setup_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_type VARCHAR(50) NOT NULL,
    platform_version VARCHAR(50),
    script_content TEXT NOT NULL,
    is_system BOOLEAN DEFAULT FALSE,       -- System-provided vs user-created
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Append-only audit log
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    action_type VARCHAR(100) NOT NULL,     -- 'agent.create', 'agent.delete', etc.
    target_type VARCHAR(50),               -- 'agent', 'credential', etc.
    target_id UUID,
    details JSONB,
    ip_address INET,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Prevent updates/deletes on audit_logs
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;
```

---

## API Endpoints

### Authentication

| Method | Endpoint         | Description                |
| ------ | ---------------- | -------------------------- |
| GET    | `/auth/login`    | Redirect to OAuth provider |
| GET    | `/auth/callback` | OAuth callback handler     |
| POST   | `/auth/logout`   | Clear session              |
| GET    | `/auth/me`       | Get current user info      |

### Agents (Active)

| Method | Endpoint                    | Description                    |
| ------ | --------------------------- | ------------------------------ |
| GET    | `/agents`                   | List user's active agents      |
| POST   | `/agents`                   | Create new agent               |
| GET    | `/agents/{id}`              | Get agent details              |
| DELETE | `/agents/{id}`              | Delete agent (destroy VM)      |
| POST   | `/agents/{id}/start`        | Start stopped agent            |
| POST   | `/agents/{id}/stop`         | Stop (pause) agent             |
| POST   | `/agents/{id}/archive`      | Save current state as template |
| POST   | `/agents/{id}/restore`      | Restore from a saved agent     |
| GET    | `/agents/{id}/status`       | Get real-time status           |
| GET    | `/agents/{id}/files`        | Browse VM filesystem           |
| GET    | `/agents/{id}/files/{path}` | Download file from VM          |
| PUT    | `/agents/{id}/files/{path}` | Upload file to VM              |
| POST   | `/agents/{id}/chat`         | Send message to agent gateway  |
| GET    | `/agents/{id}/ssh`          | Get SSH connection details     |

### Saved Agents

| Method | Endpoint                    | Description                       |
| ------ | --------------------------- | --------------------------------- |
| GET    | `/saved-agents`             | List all saved agents             |
| GET    | `/saved-agents/starred`     | List starred templates            |
| GET    | `/saved-agents/{id}`        | Get saved agent details           |
| PUT    | `/saved-agents/{id}`        | Update saved agent metadata       |
| DELETE | `/saved-agents/{id}`        | Delete saved agent                |
| POST   | `/saved-agents/{id}/star`   | Star a saved agent                |
| DELETE | `/saved-agents/{id}/star`   | Unstar a saved agent              |
| POST   | `/saved-agents/{id}/copy`   | Duplicate saved agent             |
| POST   | `/saved-agents/{id}/deploy` | Create active agent from template |

### Credentials

| Method | Endpoint                             | Description                  |
| ------ | ------------------------------------ | ---------------------------- |
| GET    | `/credentials`                       | List user's credentials      |
| POST   | `/credentials`                       | Add new credential           |
| GET    | `/credentials/{id}`                  | Get credential metadata      |
| DELETE | `/credentials/{id}`                  | Delete credential            |
| POST   | `/agents/{id}/credentials/{cred_id}` | Grant credential to agent    |
| DELETE | `/agents/{id}/credentials/{cred_id}` | Revoke credential from agent |

### Audit Logs

| Method | Endpoint       | Description                        |
| ------ | -------------- | ---------------------------------- |
| GET    | `/logs`        | List user's audit logs (paginated) |
| GET    | `/logs/export` | Export logs as CSV/JSON            |

---

## Frontend Structure

```
src/
├── components/
│   ├── common/
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Modal.tsx
│   │   ├── Table.tsx
│   │   ├── StatusBadge.tsx
│   │   └── LoadingSpinner.tsx
│   ├── layout/
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   └── Layout.tsx
│   ├── agents/
│   │   ├── AgentCard.tsx
│   │   ├── AgentList.tsx
│   │   ├── AgentDetail.tsx
│   │   ├── AgentChat.tsx
│   │   ├── AgentFileBrowser.tsx
│   │   ├── CreateAgentModal.tsx
│   │   └── AgentActions.tsx
│   ├── saved-agents/
│   │   ├── SavedAgentCard.tsx
│   │   ├── SavedAgentList.tsx
│   │   └── SavedAgentDetail.tsx
│   ├── credentials/
│   │   ├── CredentialList.tsx
│   │   ├── CredentialForm.tsx
│   │   └── CredentialGrant.tsx
│   └── logs/
│       ├── AuditLogTable.tsx
│       └── LogFilters.tsx
├── pages/
│   ├── Landing.tsx
│   ├── Dashboard.tsx
│   ├── AgentDetail.tsx
│   ├── SavedAgents.tsx
│   ├── SavedAgentDetail.tsx
│   ├── Credentials.tsx
│   └── AuditLogs.tsx
├── hooks/
│   ├── useAuth.ts
│   ├── useAgents.ts
│   ├── useSavedAgents.ts
│   └── useCredentials.ts
├── services/
│   └── api.ts
├── context/
│   └── AuthContext.tsx
├── types/
│   └── index.ts
└── App.tsx
```

---

## Agent Lifecycle

### Creating an Agent

```
1. User selects "Create Agent"
2. User chooses:
   - Platform (openclaw)
   - Template (blank or saved agent)
   - Name
   - Initial credentials to grant
3. Backend:
   a. Creates VM via VMProvider
   b. Creates data exchange bucket via StorageProvider
   c. Creates scoped credentials for the bucket
   d. Runs setup script on VM (installs Node.js, pnpm, openclaw)
   e. If template: copies config files to VM
   f. Copies granted credentials to VM
   g. Starts openclaw gateway daemon
   h. Records in database
   i. Logs action to audit log
4. Frontend polls for VM status until ready
5. User can now interact with agent
```

### Setup Script Example (openclaw)

```bash
#!/bin/bash
set -e

# Install Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install pnpm
npm install -g pnpm

# Install openclaw
pnpm add -g openclaw@latest

# Create config directory
mkdir -p ~/.openclaw

# Run onboarding (credentials injected separately)
openclaw onboard --install-daemon

# Start gateway
systemctl --user enable openclaw-gateway
systemctl --user start openclaw-gateway
```

---

## Security Model

### User OAuth Credentials for Cloud Operations

Zerg Rush uses **user OAuth credentials** for all cloud operations rather than application-default credentials. This provides better security isolation and audit trails.

#### OAuth Scopes

**GCP:**

- `openid`, `email`, `profile` - User identity
- `https://www.googleapis.com/auth/cloud-platform` - Full GCP API access

**Azure:**

- `openid`, `email`, `profile`, `offline_access`, `User.Read` - User identity
- Resource-specific tokens obtained via refresh token:
  - `https://management.azure.com/.default` - ARM management
  - `https://storage.azure.com/.default` - Blob storage
  - `https://vault.azure.net/.default` - Key Vault

#### Token Storage

OAuth tokens are stored encrypted in the database:

```
User ────────> UserOAuthToken (encrypted with Fernet)
                 │
                 ├── access_token_encrypted
                 ├── refresh_token_encrypted
                 ├── expires_at
                 ├── scopes
                 ├── project_id (GCP)
                 ├── subscription_id (Azure)
                 └── tenant_id (Azure)
```

#### Token Refresh

Tokens are automatically refreshed when:

1. Access token expires within 5 minutes of a request
2. Cloud API returns 401 Unauthorized

#### Security Boundaries

| Operation          | Credentials Used                |
| ------------------ | ------------------------------- |
| Database access    | Application Default Credentials |
| OAuth login flow   | Application Default Credentials |
| VM operations      | User OAuth Token                |
| Storage operations | User OAuth Token                |
| Secret operations  | User OAuth Token                |

This ensures users can only access cloud resources they have permission for in their own GCP project or Azure subscription.

### Credential Flow

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    User     │     │  Zerg Rush API  │     │  Secret Store   │
└──────┬──────┘     └────────┬────────┘     └────────┬────────┘
       │                     │                       │
       │ Add credential      │                       │
       │────────────────────▶│                       │
       │                     │  Store secret         │
       │                     │──────────────────────▶│
       │                     │  Return reference     │
       │                     │◀──────────────────────│
       │                     │                       │
       │ Grant to agent      │                       │
       │────────────────────▶│                       │
       │                     │  Fetch secret         │
       │                     │──────────────────────▶│
       │                     │  Return value         │
       │                     │◀──────────────────────│
       │                     │                       │
       │                     │  ┌─────────────────┐  │
       │                     │  │   Agent VM      │  │
       │                     │──│ Write to config │  │
       │                     │  │ Delete from API │  │
       │                     │  └─────────────────┘  │
       │                     │                       │
```

### Isolation Guarantees

1. **VM Isolation**: Each agent runs in a separate VM with no network access to other VMs
2. **Storage Isolation**: Each agent has its own bucket; credentials are scoped to that bucket only
3. **Credential Isolation**: Agents only receive credentials explicitly granted to them
4. **No Lateral Movement**: Agent VMs cannot access the control plane's database or secrets
5. **Network Segmentation**: Agent VMs are in a separate VPC/network from the control plane

### Agent Chat Proxy Architecture

Agent gateways are **never exposed** to the public internet. All communication with agents flows through the backend:

```
┌──────────┐      HTTPS       ┌─────────────────┐   Internal Network   ┌───────────────┐
│ Frontend │ ───────────────▶ │  Backend API    │ ──────────────────▶  │   Agent VM    │
│          │                  │                 │   (private IP only)  │  :18789       │
│ POST     │                  │ POST            │                      │  openclaw     │
│ /agents/ │                  │ Validates user  │                      │  gateway      │
│ {id}/chat│                  │ owns agent,     │                      │               │
│          │                  │ forwards to     │                      │               │
│          │ ◀─────────────── │ vm_internal_ip  │ ◀────────────────── │               │
│ Response │      HTTPS       │                 │   Internal Network   │               │
└──────────┘                  └─────────────────┘                      └───────────────┘
```

Benefits:

- Agent VMs have no public IP addresses
- Backend validates user authorization before forwarding
- All traffic is logged for audit purposes
- Compromised agents cannot be accessed by external attackers

---

## Project Structure

```
zerg-rush/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── config.py               # Configuration management
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes/
│   │   │   │   ├── auth.py
│   │   │   │   ├── agents.py
│   │   │   │   ├── saved_agents.py
│   │   │   │   ├── credentials.py
│   │   │   │   └── logs.py
│   │   │   └── dependencies.py     # Auth, DB session, etc.
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── agent_service.py
│   │   │   ├── credential_service.py
│   │   │   ├── template_service.py
│   │   │   └── audit_service.py
│   │   ├── cloud/
│   │   │   ├── __init__.py
│   │   │   ├── interfaces.py       # Abstract base classes
│   │   │   ├── factory.py          # Provider factory
│   │   │   ├── gcp/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── vm.py
│   │   │   │   ├── storage.py
│   │   │   │   ├── secrets.py
│   │   │   │   └── identity.py
│   │   │   ├── aws/                # Future
│   │   │   └── azure/              # Future
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── agent.py
│   │   │   ├── saved_agent.py
│   │   │   ├── credential.py
│   │   │   └── audit_log.py
│   │   └── db/
│   │       ├── __init__.py
│   │       ├── session.py
│   │       └── migrations/
│   ├── scripts/
│   │   └── setup/
│   │       └── openclaw.sh
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   └── [structure above]
│   ├── public/
│   ├── package.json
│   └── Dockerfile
├── infrastructure/
│   ├── terraform/
│   │   ├── gcp/
│   │   ├── aws/                    # Future
│   │   └── azure/                  # Future
│   └── docker-compose.yml          # Local development
├── .clarity-protocol/
│   ├── problem.md
│   └── solution/
│       ├── user-perspective.md
│       └── architecture.md
└── README.md
```

---

## Development Phases

### Phase 1: Foundation (MVP)

- [ ] Project scaffolding (backend + frontend)
- [ ] Database schema and migrations
- [ ] OAuth authentication (Google)
- [ ] GCP cloud provider implementations
- [ ] Basic agent CRUD (create, list, delete)
- [ ] Agent VM lifecycle (start, stop)
- [ ] Simple dashboard UI

### Phase 2: Core Features

- [ ] Credential management
- [ ] Agent chat interface
- [ ] File browser for agent VMs
- [ ] Save agent as template
- [ ] Create agent from template
- [ ] Audit logging

### Phase 3: Polish

- [ ] Bulk operations on saved agents
- [ ] SSH access to agents
- [ ] Agent status monitoring
- [ ] Error handling and retry logic
- [ ] Production deployment configuration

### Phase 4: Multi-Cloud

- [ ] AWS provider implementation
- [ ] Azure provider implementation
- [ ] Provider selection in UI

### Phase 5: Advanced Features

- [ ] Auto-pause idle VMs
- [ ] Cost tracking
- [ ] Agent metrics/analytics
- [ ] Additional agent platforms

---

## Design Decisions

The following decisions have been made for this project:

### 1. Authentication Providers

**Decision**: Support multiple OAuth providers, starting with Google.

- MVP: Google OAuth only
- Future: Add Microsoft, GitHub as additional providers
- Users can link multiple OAuth accounts to a single Zerg Rush account

### 2. VM Size Configuration

**Decision**: Users can select VM sizes, with a sensible default.

- Provide a dropdown of available VM sizes per cloud provider
- Default to a small/medium instance suitable for most agents
- Store selected size in agent configuration

### 3. Agent Chat Networking

**Decision**: Proxy all agent communication through the backend.

- Agent gateways (port 18789) are **never exposed** to the public internet
- All chat messages flow: Frontend → Backend API → Agent VM (internal network)
- This is critical for security—compromised agents cannot be accessed externally
- Adds some latency but provides essential isolation

### 4. Template Sharing

**Decision**: Templates are private per user (for now).

- MVP: Each user's templates are visible only to them
- Future consideration: Add optional template sharing between users

### 5. Cost Awareness

**Decision**: Deferred to future phases.

- Not included in MVP
- Future: Show estimated/actual costs for running agents
