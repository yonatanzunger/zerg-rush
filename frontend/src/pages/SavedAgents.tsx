import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Star, Copy, Trash2, Play } from 'lucide-react'
import { savedAgents, agents } from '../services/api'
import Button from '../components/common/Button'
import Card, { CardBody } from '../components/common/Card'

export default function SavedAgents() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['saved-agents'],
    queryFn: () => savedAgents.list(),
  })

  const starMutation = useMutation({
    mutationFn: ({ id, starred }: { id: string; starred: boolean }) =>
      starred ? savedAgents.unstar(id) : savedAgents.star(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-agents'] })
    },
  })

  const copyMutation = useMutation({
    mutationFn: (id: string) => savedAgents.copy(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-agents'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => savedAgents.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-agents'] })
    },
  })

  const deployMutation = useMutation({
    mutationFn: (template: { id: string; name: string; platform_type: string }) =>
      agents.create({
        name: `${template.name} Agent`,
        platform_type: template.platform_type,
        template_id: template.id,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Saved Agents</h1>
        <p className="text-gray-600 mt-1">Manage your agent templates and snapshots</p>
      </div>

      {data?.saved_agents.length === 0 ? (
        <Card>
          <CardBody className="text-center py-12">
            <p className="text-gray-500">No saved agents yet</p>
            <p className="text-sm text-gray-400 mt-2">
              Archive an active agent to create a saved template
            </p>
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data?.saved_agents.map((saved) => (
            <Card key={saved.id}>
              <CardBody>
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="font-semibold text-gray-900">{saved.name}</h3>
                    <p className="text-sm text-gray-500">{saved.platform_type}</p>
                  </div>
                  <button
                    onClick={() => starMutation.mutate({ id: saved.id, starred: saved.is_starred })}
                    className={`p-1 rounded ${
                      saved.is_starred ? 'text-yellow-500' : 'text-gray-300 hover:text-yellow-500'
                    }`}
                  >
                    <Star className="h-5 w-5" fill={saved.is_starred ? 'currentColor' : 'none'} />
                  </button>
                </div>
                {saved.description && (
                  <p className="text-sm text-gray-600 mb-4">{saved.description}</p>
                )}
                <p className="text-xs text-gray-400 mb-4">
                  Created {new Date(saved.created_at).toLocaleDateString()}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() =>
                      deployMutation.mutate({
                        id: saved.id,
                        name: saved.name,
                        platform_type: saved.platform_type,
                      })
                    }
                    isLoading={deployMutation.isPending}
                  >
                    <Play className="h-4 w-4 mr-1" />
                    Deploy
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => copyMutation.mutate(saved.id)}
                    isLoading={copyMutation.isPending}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600 hover:bg-red-50"
                    onClick={() => {
                      if (confirm('Delete this saved agent?')) {
                        deleteMutation.mutate(saved.id)
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
