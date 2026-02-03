// User types
export interface User {
  id: string
  email: string
  name: string
  created_at: string
}

// Agent types
export interface Agent {
  id: string
  name: string
  vm_id: string
  vm_size: string
  vm_status: AgentStatus
  vm_internal_ip: string | null
  bucket_id: string
  current_task: string | null
  platform_type: string
  platform_version: string | null
  template_id: string | null
  gateway_port: number
  created_at: string
  updated_at: string
}

export type AgentStatus =
  | 'creating'
  | 'running'
  | 'stopping'
  | 'stopped'
  | 'starting'
  | 'deleting'
  | 'deleted'
  | 'error'

export interface CreateAgentRequest {
  name: string
  platform_type?: string
  vm_size?: string
  template_id?: string
  credential_ids?: string[]
}

// Saved Agent types
export interface SavedAgent {
  id: string
  name: string
  platform_type: string
  is_starred: boolean
  description: string | null
  config_snapshot: Record<string, unknown> | null
  source_agent_id: string | null
  created_at: string
}

// Credential types
export interface Credential {
  id: string
  name: string
  type: CredentialType
  description: string | null
  created_at: string
}

export type CredentialType = 'llm' | 'cloud' | 'utility'

export interface CreateCredentialRequest {
  name: string
  type: CredentialType
  description?: string
  value: string
}

// Audit Log types
export interface AuditLog {
  id: string
  action_type: string
  target_type: string | null
  target_id: string | null
  details: Record<string, unknown> | null
  ip_address: string | null
  timestamp: string
}

// API Response types
export interface ListResponse<T> {
  total: number
}

export interface AgentListResponse extends ListResponse<Agent> {
  agents: Agent[]
}

export interface SavedAgentListResponse extends ListResponse<SavedAgent> {
  saved_agents: SavedAgent[]
}

export interface CredentialListResponse extends ListResponse<Credential> {
  credentials: Credential[]
}

export interface AuditLogListResponse {
  logs: AuditLog[]
  total: number
  has_more: boolean
}
