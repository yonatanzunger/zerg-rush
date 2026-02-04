import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Play, Square, Archive, Trash2, Send, RefreshCw, ExternalLink, Terminal, Copy } from 'lucide-react'
import { agents } from '../services/api'
import Button from '../components/common/Button'
import Card, { CardBody, CardHeader } from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import Modal from '../components/common/Modal'
import OperationProgress from '../components/common/OperationProgress'
import { useStreamingOperation } from '../hooks/useStreamingOperation'
import type { Agent } from '../types'

export default function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [chatMessage, setChatMessage] = useState('')
  const [chatHistory, setChatHistory] = useState<{ role: 'user' | 'agent'; content: string }[]>([])
  const [isProgressModalOpen, setIsProgressModalOpen] = useState(false)
  const [progressTitle, setProgressTitle] = useState('')

  // Streaming operation hook for long-running operations
  const streamingOp = useStreamingOperation<Agent>()

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => agents.get(agentId!),
    enabled: !!agentId,
    refetchInterval: 5000, // Poll for status updates
  })

  const archiveMutation = useMutation({
    mutationFn: () => agents.archive(agentId!),
    onSuccess: (data) => {
      alert(`Saved as "${data.name}"`)
      queryClient.invalidateQueries({ queryKey: ['saved-agents'] })
    },
  })

  // Handle streaming agent start
  const handleStartStreaming = async () => {
    if (!agent) return
    setProgressTitle(`Starting agent "${agent.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    const result = await streamingOp.executePost(agents.streaming.startUrl(agentId!))

    if (result) {
      queryClient.invalidateQueries({ queryKey: ['agent', agentId] })
    }
  }

  // Handle streaming agent stop
  const handleStopStreaming = async () => {
    if (!agent) return
    setProgressTitle(`Stopping agent "${agent.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    const result = await streamingOp.executePost(agents.streaming.stopUrl(agentId!))

    if (result) {
      queryClient.invalidateQueries({ queryKey: ['agent', agentId] })
    }
  }

  // Handle streaming agent deletion
  const handleDeleteStreaming = async () => {
    if (!agent) return
    if (!confirm('Are you sure you want to delete this agent? This cannot be undone.')) {
      return
    }

    setProgressTitle(`Deleting agent "${agent.name}"...`)
    setIsProgressModalOpen(true)
    streamingOp.reset()

    const success = await streamingOp.executeDelete(agents.streaming.deleteUrl(agentId!))

    // Invalidate and navigate on success
    queryClient.invalidateQueries({ queryKey: ['agents'] })
    if (success) {
      // Delay navigation slightly to let user see completion
      setTimeout(() => navigate('/dashboard'), 1500)
    }
  }

  const chatMutation = useMutation({
    mutationFn: (message: string) => agents.chat(agentId!, message),
    onSuccess: (data) => {
      setChatHistory((prev) => [...prev, { role: 'agent', content: data.response }])
    },
  })

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault()
    if (!chatMessage.trim()) return
    setChatHistory((prev) => [...prev, { role: 'user', content: chatMessage }])
    chatMutation.mutate(chatMessage)
    setChatMessage('')
  }

  const handleRefreshStatus = () => {
    queryClient.invalidateQueries({ queryKey: ['agent', agentId] })
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Agent not found</p>
        <Button variant="secondary" className="mt-4" onClick={() => navigate('/dashboard')}>
          Back to Dashboard
        </Button>
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <button
          onClick={() => navigate('/dashboard')}
          className="flex items-center text-gray-600 hover:text-gray-900 mb-4"
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to Dashboard
        </button>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold text-gray-900">{agent.name}</h1>
            <StatusBadge status={agent.vm_status} />
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleRefreshStatus}>
              <RefreshCw className="h-4 w-4" />
            </Button>
            {agent.vm_status === 'stopped' && (
              <Button onClick={handleStartStreaming} isLoading={streamingOp.isLoading}>
                <Play className="h-4 w-4 mr-2" />
                Start
              </Button>
            )}
            {agent.vm_status === 'running' && (
              <Button variant="secondary" onClick={handleStopStreaming} isLoading={streamingOp.isLoading}>
                <Square className="h-4 w-4 mr-2" />
                Stop
              </Button>
            )}
            <Button variant="secondary" onClick={() => archiveMutation.mutate()} isLoading={archiveMutation.isPending}>
              <Archive className="h-4 w-4 mr-2" />
              Archive
            </Button>
            <Button
              variant="danger"
              onClick={handleDeleteStreaming}
              isLoading={streamingOp.isLoading}
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Agent Info */}
        <Card>
          <CardHeader>
            <h2 className="font-semibold text-gray-900">Agent Details</h2>
          </CardHeader>
          <CardBody>
            <dl className="space-y-4">
              <div>
                <dt className="text-sm text-gray-500">Platform</dt>
                <dd className="text-gray-900">{agent.platform_type}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">VM Size</dt>
                <dd className="text-gray-900">{agent.vm_size}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">VM ID</dt>
                <dd className="text-gray-900 font-mono text-sm">{agent.vm_id}</dd>
              </div>
              {agent.vm_internal_ip && (
                <div>
                  <dt className="text-sm text-gray-500">Internal IP</dt>
                  <dd className="text-gray-900 font-mono text-sm">{agent.vm_internal_ip}</dd>
                </div>
              )}
              <div>
                <dt className="text-sm text-gray-500">Gateway Port</dt>
                <dd className="text-gray-900">{agent.gateway_port}</dd>
              </div>
              {(agent.cloud_console_url || agent.ssh_url || agent.ssh_command) && (
                <div>
                  <dt className="text-sm text-gray-500">Cloud Resources</dt>
                  <dd className="flex flex-col gap-2 mt-1">
                    {agent.cloud_console_url && (
                      <a
                        href={agent.cloud_console_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-700"
                      >
                        <ExternalLink className="h-4 w-4" />
                        View in {agent.cloud_provider.toUpperCase()} Console
                      </a>
                    )}
                    {agent.ssh_url && (
                      <a
                        href={agent.ssh_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-700"
                      >
                        <Terminal className="h-4 w-4" />
                        Open SSH Terminal
                      </a>
                    )}
                    {agent.ssh_command && (
                      <div className="flex items-center gap-2">
                        <code className="text-sm bg-gray-100 px-2 py-1 rounded font-mono">
                          {agent.ssh_command}
                        </code>
                        <button
                          onClick={() => {
                            navigator.clipboard.writeText(agent.ssh_command!)
                          }}
                          className="p-1 text-gray-500 hover:text-gray-700"
                          title="Copy to clipboard"
                        >
                          <Copy className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </dd>
                </div>
              )}
              <div>
                <dt className="text-sm text-gray-500">Created</dt>
                <dd className="text-gray-900">
                  {new Date(agent.created_at).toLocaleString()}
                </dd>
              </div>
            </dl>
          </CardBody>
        </Card>

        {/* Chat */}
        <Card className="flex flex-col max-h-[600px]">
          <CardHeader>
            <h2 className="font-semibold text-gray-900">Chat with Agent</h2>
          </CardHeader>
          <CardBody className="flex-1 overflow-y-auto">
            {agent.vm_status !== 'running' ? (
              <div className="text-center py-8 text-gray-500">
                Agent must be running to chat
              </div>
            ) : chatHistory.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                Start a conversation with your agent
              </div>
            ) : (
              <div className="space-y-4">
                {chatHistory.map((msg, i) => (
                  <div
                    key={i}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-2 ${
                        msg.role === 'user'
                          ? 'bg-primary-600 text-white'
                          : 'bg-gray-100 text-gray-900'
                      }`}
                    >
                      {msg.content}
                    </div>
                  </div>
                ))}
                {chatMutation.isPending && (
                  <div className="flex justify-start">
                    <div className="bg-gray-100 rounded-lg px-4 py-2 text-gray-500">
                      Thinking...
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardBody>
          {agent.vm_status === 'running' && (
            <div className="border-t border-gray-200 p-4">
              <form onSubmit={handleSendMessage} className="flex gap-2">
                <input
                  type="text"
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  placeholder="Type a message..."
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  disabled={chatMutation.isPending}
                />
                <Button type="submit" isLoading={chatMutation.isPending}>
                  <Send className="h-4 w-4" />
                </Button>
              </form>
            </div>
          )}
        </Card>
      </div>

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
