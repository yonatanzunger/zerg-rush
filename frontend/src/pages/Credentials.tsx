import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Key, Cloud, Cpu } from 'lucide-react'
import { credentials } from '../services/api'
import Button from '../components/common/Button'
import Card, { CardBody } from '../components/common/Card'
import Modal from '../components/common/Modal'
import type { CredentialType, CreateCredentialRequest } from '../types'

const typeIcons: Record<CredentialType, typeof Key> = {
  llm: Cpu,
  cloud: Cloud,
  utility: Key,
}

const typeLabels: Record<CredentialType, string> = {
  llm: 'LLM Provider',
  cloud: 'Cloud Provider',
  utility: 'Utility Service',
}

export default function Credentials() {
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['credentials'],
    queryFn: () => credentials.list(),
  })

  const createMutation = useMutation({
    mutationFn: (data: CreateCredentialRequest) => credentials.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      setIsCreateModalOpen(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => credentials.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
    },
  })

  const handleCreate = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)
    createMutation.mutate({
      name: formData.get('name') as string,
      type: formData.get('type') as CredentialType,
      description: formData.get('description') as string || undefined,
      value: formData.get('value') as string,
    })
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Credentials</h1>
          <p className="text-gray-600 mt-1">Manage credentials that can be granted to agents</p>
        </div>
        <Button onClick={() => setIsCreateModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Credential
        </Button>
      </div>

      {data?.credentials.length === 0 ? (
        <Card>
          <CardBody className="text-center py-12">
            <Key className="h-12 w-12 mx-auto text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No credentials</h3>
            <p className="text-gray-500 mb-4">Add credentials that agents can use</p>
            <Button onClick={() => setIsCreateModalOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add Credential
            </Button>
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data?.credentials.map((cred) => {
            const Icon = typeIcons[cred.type]
            return (
              <Card key={cred.id}>
                <CardBody>
                  <div className="flex items-start gap-4">
                    <div className="h-10 w-10 rounded-lg bg-gray-100 flex items-center justify-center">
                      <Icon className="h-5 w-5 text-gray-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-gray-900 truncate">{cred.name}</h3>
                      <p className="text-sm text-gray-500">{typeLabels[cred.type]}</p>
                      {cred.description && (
                        <p className="text-sm text-gray-600 mt-2 truncate">{cred.description}</p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-red-600 hover:bg-red-50"
                      onClick={() => {
                        if (confirm('Delete this credential?')) {
                          deleteMutation.mutate(cred.id)
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardBody>
              </Card>
            )
          })}
        </div>
      )}

      {/* Create Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="Add Credential"
      >
        <form onSubmit={handleCreate}>
          <div className="space-y-4">
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                Name
              </label>
              <input
                type="text"
                id="name"
                name="name"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="My API Key"
              />
            </div>
            <div>
              <label htmlFor="type" className="block text-sm font-medium text-gray-700 mb-1">
                Type
              </label>
              <select
                id="type"
                name="type"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              >
                <option value="llm">LLM Provider</option>
                <option value="cloud">Cloud Provider</option>
                <option value="utility">Utility Service</option>
              </select>
            </div>
            <div>
              <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
                Description (optional)
              </label>
              <input
                type="text"
                id="description"
                name="description"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="API key for..."
              />
            </div>
            <div>
              <label htmlFor="value" className="block text-sm font-medium text-gray-700 mb-1">
                Secret Value
              </label>
              <input
                type="password"
                id="value"
                name="value"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono"
                placeholder="sk-..."
              />
              <p className="text-xs text-gray-500 mt-1">
                This value will be encrypted and stored securely
              </p>
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => setIsCreateModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={createMutation.isPending}>
              Add Credential
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
