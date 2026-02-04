import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Plus, Bot, Star, Play, Square, Trash2 } from 'lucide-react'
import { agents, savedAgents } from '../services/api'
import Button from '../components/common/Button'
import Card, { CardBody } from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import Modal from '../components/common/Modal'
import OperationProgress from '../components/common/OperationProgress'
import { useStreamingOperation } from '../hooks/useStreamingOperation'
import type { Agent, CreateAgentRequest } from '../types'

export default function Dashboard() {
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [isProgressModalOpen, setIsProgressModalOpen] = useState(false)
  const [progressTitle, setProgressTitle] = useState('')
  const queryClient = useQueryClient()

  // Streaming operation hook for long-running operations
  const streamingOp = useStreamingOperation<Agent>()

  const { data: agentsData, isLoading: agentsLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agents.list(),
  })

  const { data: starredData } = useQuery({
    queryKey: ['saved-agents', 'starred'],
    queryFn: () => savedAgents.getStarred(),
  })


  // Handle streaming agent creation
  const handleCreateAgentStreaming = async (data: CreateAgentRequest) => {
    setIsCreateModalOpen(false)
    setProgressTitle(`Creating agent "${data.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    const result = await streamingOp.executePost(agents.streaming.createUrl(), data)

    if (result) {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    }
  }

  // Handle streaming agent deletion
  const handleDeleteAgentStreaming = async (agent: Agent) => {
    if (!confirm(`Are you sure you want to delete "${agent.name}"?`)) {
      return
    }

    setProgressTitle(`Deleting agent "${agent.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    await streamingOp.executeDelete(agents.streaming.deleteUrl(agent.id))
    queryClient.invalidateQueries({ queryKey: ['agents'] })
  }

  // Handle streaming agent start
  const handleStartAgentStreaming = async (agent: Agent) => {
    setProgressTitle(`Starting agent "${agent.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    const result = await streamingOp.executePost(agents.streaming.startUrl(agent.id))

    if (result) {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    }
  }

  // Handle streaming agent stop
  const handleStopAgentStreaming = async (agent: Agent) => {
    setProgressTitle(`Stopping agent "${agent.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    const result = await streamingOp.executePost(agents.streaming.stopUrl(agent.id))

    if (result) {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    }
  }

  const handleCreateAgent = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)
    const data: CreateAgentRequest = {
      name: formData.get('name') as string,
      platform_type: 'openclaw',
    }
    // Use streaming version
    handleCreateAgentStreaming(data)
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-600 mt-1">Manage your active agents</p>
        </div>
        <Button onClick={() => setIsCreateModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          New Agent
        </Button>
      </div>

      {/* Starred Templates */}
      {starredData && starredData.saved_agents.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Star className="h-5 w-5 text-yellow-500" />
            Templates
          </h2>
          <div className="flex gap-4 overflow-x-auto pb-2">
            {starredData.saved_agents.map((template) => (
              <Card
                key={template.id}
                className="flex-shrink-0 w-48 cursor-pointer hover:border-primary-300"
                onClick={() => {
                  handleCreateAgentStreaming({
                    name: `${template.name} Agent`,
                    platform_type: template.platform_type,
                    template_id: template.id,
                  })
                }}
              >
                <CardBody className="text-center py-6">
                  <Bot className="h-8 w-8 mx-auto text-primary-600 mb-2" />
                  <p className="font-medium text-gray-900 truncate">{template.name}</p>
                  <p className="text-sm text-gray-500">{template.platform_type}</p>
                </CardBody>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Active Agents */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Active Agents</h2>
        {agentsLoading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
          </div>
        ) : agentsData?.agents.length === 0 ? (
          <Card>
            <CardBody className="text-center py-12">
              <Bot className="h-12 w-12 mx-auto text-gray-400 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">No active agents</h3>
              <p className="text-gray-500 mb-4">Create your first agent to get started</p>
              <Button onClick={() => setIsCreateModalOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Create Agent
              </Button>
            </CardBody>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {agentsData?.agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onStart={() => handleStartAgentStreaming(agent)}
                onStop={() => handleStopAgentStreaming(agent)}
                onDelete={() => handleDeleteAgentStreaming(agent)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Create Agent Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="Create New Agent"
      >
        <form onSubmit={handleCreateAgent}>
          <div className="space-y-4">
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                Agent Name
              </label>
              <input
                type="text"
                id="name"
                name="name"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="My Agent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Platform
              </label>
              <div className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-700">
                openclaw
              </div>
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => setIsCreateModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={streamingOp.isLoading}>
              Create Agent
            </Button>
          </div>
        </form>
      </Modal>

      {/* Progress Modal for streaming operations */}
      <Modal
        isOpen={isProgressModalOpen}
        onClose={() => {
          if (!streamingOp.isLoading) {
            setIsProgressModalOpen(false)
          }
        }}
        title={progressTitle}
      >
        <OperationProgress
          events={streamingOp.events}
          isLoading={streamingOp.isLoading}
          error={streamingOp.error}
          isComplete={!!streamingOp.result || (streamingOp.events.some(e => e.type === 'complete') && !streamingOp.error)}
          maxHeight="400px"
        />
        <div className="mt-4 flex justify-end">
          <Button
            variant={streamingOp.error ? 'secondary' : 'primary'}
            onClick={() => setIsProgressModalOpen(false)}
            disabled={streamingOp.isLoading}
          >
            {streamingOp.isLoading ? 'Please wait...' : streamingOp.error ? 'Close' : 'Done'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}

function AgentCard({
  agent,
  onStart,
  onStop,
  onDelete,
}: {
  agent: Agent
  onStart: () => void
  onStop: () => void
  onDelete: () => void
}) {
  return (
    <Card>
      <CardBody>
        <div className="flex items-start justify-between mb-4">
          <Link to={`/agents/${agent.id}`} className="flex-1">
            <h3 className="font-semibold text-gray-900 hover:text-primary-600">
              {agent.name}
            </h3>
            <p className="text-sm text-gray-500">{agent.platform_type}</p>
          </Link>
          <StatusBadge status={agent.vm_status} />
        </div>
        {agent.current_task && (
          <p className="text-sm text-gray-600 mb-4 truncate">{agent.current_task}</p>
        )}
        <div className="flex items-center gap-2">
          {agent.vm_status === 'stopped' && (
            <Button size="sm" variant="ghost" onClick={onStart}>
              <Play className="h-4 w-4 mr-1" />
              Start
            </Button>
          )}
          {agent.vm_status === 'running' && (
            <Button size="sm" variant="ghost" onClick={onStop}>
              <Square className="h-4 w-4 mr-1" />
              Stop
            </Button>
          )}
          <Button size="sm" variant="ghost" className="text-red-600 hover:bg-red-50" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
