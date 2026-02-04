import axios from 'axios'
import type {
  User,
  Agent,
  AgentListResponse,
  SavedAgent,
  SavedAgentListResponse,
  Credential,
  CreateCredentialRequest,
  CredentialListResponse,
  AuditLogListResponse,
} from '../types'

const API_BASE = '/api'

const api = axios.create({
  baseURL: API_BASE,
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

// Auth
export const auth = {
  getLoginUrl: () => `${API_BASE}/auth/login`,
  logout: () => api.post('/auth/logout'),
  me: () => api.get<User>('/auth/me').then((r) => r.data),
}

// Agents
export const agents = {
  list: (skip = 0, limit = 20) =>
    api.get<AgentListResponse>('/agents', { params: { skip, limit } }).then((r) => r.data),

  get: (id: string) =>
    api.get<Agent>(`/agents/${id}`).then((r) => r.data),

  getStatus: (id: string) =>
    api.get<Agent>(`/agents/${id}/status`).then((r) => r.data),

  archive: (id: string, name?: string) =>
    api.post<{ id: string; name: string }>(`/agents/${id}/archive`, null, { params: { name } }).then((r) => r.data),

  chat: (id: string, message: string) =>
    api.post<{ response: string }>(`/agents/${id}/chat`, { message }).then((r) => r.data),

  // Streaming endpoints - these return URLs for use with useStreamingOperation hook
  streaming: {
    createUrl: () => `${API_BASE}/agents/stream`,
    deleteUrl: (id: string) => `${API_BASE}/agents/${id}/stream`,
    startUrl: (id: string) => `${API_BASE}/agents/${id}/start/stream`,
    stopUrl: (id: string) => `${API_BASE}/agents/${id}/stop/stream`,
  },
}

// Saved Agents
export const savedAgents = {
  list: (starredOnly = false, skip = 0, limit = 20) =>
    api.get<SavedAgentListResponse>('/saved-agents', { params: { starred_only: starredOnly, skip, limit } }).then((r) => r.data),

  getStarred: () =>
    api.get<SavedAgentListResponse>('/saved-agents/starred').then((r) => r.data),

  get: (id: string) =>
    api.get<SavedAgent>(`/saved-agents/${id}`).then((r) => r.data),

  update: (id: string, data: { name?: string; description?: string }) =>
    api.put<SavedAgent>(`/saved-agents/${id}`, data).then((r) => r.data),

  delete: (id: string) =>
    api.delete(`/saved-agents/${id}`),

  star: (id: string) =>
    api.post<SavedAgent>(`/saved-agents/${id}/star`).then((r) => r.data),

  unstar: (id: string) =>
    api.delete<SavedAgent>(`/saved-agents/${id}/star`).then((r) => r.data),

  copy: (id: string, name?: string) =>
    api.post<SavedAgent>(`/saved-agents/${id}/copy`, null, { params: { name } }).then((r) => r.data),
}

// Credentials
export const credentials = {
  list: (type?: string) =>
    api.get<CredentialListResponse>('/credentials', { params: { type } }).then((r) => r.data),

  get: (id: string) =>
    api.get<Credential>(`/credentials/${id}`).then((r) => r.data),

  create: (data: CreateCredentialRequest) =>
    api.post<Credential>('/credentials', data).then((r) => r.data),

  delete: (id: string) =>
    api.delete(`/credentials/${id}`),
}

// Audit Logs
export const logs = {
  list: (actionType?: string, targetType?: string, skip = 0, limit = 50) =>
    api.get<AuditLogListResponse>('/logs', { params: { action_type: actionType, target_type: targetType, skip, limit } }).then((r) => r.data),

  export: (format: 'csv' | 'json' = 'csv') =>
    api.get('/logs/export', { params: { format }, responseType: 'blob' }).then((r) => r.data),
}

export default api
