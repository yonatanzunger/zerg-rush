import type { AgentStatus } from '../../types'

interface StatusBadgeProps {
  status: AgentStatus
}

const statusStyles: Record<AgentStatus, { bg: string; text: string; dot: string }> = {
  running: { bg: 'bg-green-50', text: 'text-green-700', dot: 'bg-green-500' },
  stopped: { bg: 'bg-gray-50', text: 'text-gray-700', dot: 'bg-gray-500' },
  creating: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500' },
  starting: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500' },
  stopping: { bg: 'bg-yellow-50', text: 'text-yellow-700', dot: 'bg-yellow-500' },
  deleting: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500' },
  deleted: { bg: 'bg-gray-50', text: 'text-gray-500', dot: 'bg-gray-400' },
  error: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500' },
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const styles = statusStyles[status] || statusStyles.error

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${styles.bg} ${styles.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${styles.dot} ${
        ['creating', 'starting', 'stopping', 'deleting'].includes(status) ? 'animate-pulse' : ''
      }`} />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}
