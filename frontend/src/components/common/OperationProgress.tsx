import { useEffect, useRef } from 'react'
import { AlertCircle, CheckCircle2, Loader2, ChevronRight, ChevronDown } from 'lucide-react'
import type { StreamEvent } from '../../hooks/useStreamingOperation'

interface OperationProgressProps {
  /** Array of streaming events to display */
  events: StreamEvent[]
  /** Whether the operation is currently in progress */
  isLoading: boolean
  /** Error message if the operation failed */
  error: string | null
  /** Whether the operation completed successfully */
  isComplete?: boolean
  /** Maximum height of the event list (scrollable) */
  maxHeight?: string
  /** Optional title for the progress section */
  title?: string
}

/**
 * Displays progress updates from a streaming operation.
 *
 * Shows a list of events with visual hierarchy based on depth,
 * loading spinner while in progress, and error/success states.
 */
export default function OperationProgress({
  events,
  isLoading,
  error,
  isComplete,
  maxHeight = '300px',
  title,
}: OperationProgressProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events])

  if (events.length === 0 && !isLoading && !error) {
    return null
  }

  const getEventIcon = (event: StreamEvent) => {
    switch (event.type) {
      case 'span_start':
        return <ChevronRight className="h-3 w-3 text-blue-500 flex-shrink-0" />
      case 'span_end':
        return <ChevronDown className="h-3 w-3 text-blue-500 flex-shrink-0" />
      case 'complete':
        return <CheckCircle2 className="h-3 w-3 text-green-500 flex-shrink-0" />
      case 'error':
        return <AlertCircle className="h-3 w-3 text-red-500 flex-shrink-0" />
      default:
        return <span className="w-3 h-3 flex-shrink-0" />
    }
  }

  const formatDuration = (ms: number | undefined) => {
    if (ms === undefined) return null
    if (ms < 1000) return `${Math.round(ms)}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp)
      return date.toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    } catch {
      return ''
    }
  }

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2 bg-gray-100 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-blue-600" />}
          {!isLoading && error && <AlertCircle className="h-4 w-4 text-red-600" />}
          {!isLoading && !error && isComplete && (
            <CheckCircle2 className="h-4 w-4 text-green-600" />
          )}
          <span className="text-sm font-medium text-gray-700">
            {title || (isLoading ? 'Operation in progress...' : error ? 'Operation failed' : 'Operation complete')}
          </span>
        </div>
        {events.length > 0 && (
          <span className="text-xs text-gray-500">{events.length} events</span>
        )}
      </div>

      {/* Event list */}
      <div
        ref={scrollRef}
        className="overflow-y-auto font-mono text-xs"
        style={{ maxHeight }}
      >
        <div className="p-2 space-y-0.5">
          {events.map((event, index) => (
            <div
              key={index}
              className={`flex items-start gap-1.5 py-0.5 ${
                event.type === 'error' ? 'text-red-600' : 'text-gray-700'
              } ${event.type === 'complete' ? 'text-green-700 font-medium' : ''}`}
              style={{ paddingLeft: `${(event.depth || 0) * 12}px` }}
            >
              {getEventIcon(event)}
              <span className="text-gray-400 flex-shrink-0">
                {formatTimestamp(event.timestamp)}
              </span>
              <span className="flex-1 break-words">{event.message}</span>
              {event.duration_ms !== undefined && (
                <span className="text-gray-400 flex-shrink-0">
                  {formatDuration(event.duration_ms)}
                </span>
              )}
            </div>
          ))}

          {/* Loading indicator at the bottom */}
          {isLoading && (
            <div className="flex items-center gap-1.5 py-0.5 text-gray-500">
              <Loader2 className="h-3 w-3 animate-spin flex-shrink-0" />
              <span>Waiting for updates...</span>
            </div>
          )}
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="px-4 py-3 bg-red-50 border-t border-red-100">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-800">Error</p>
              <p className="text-sm text-red-700 mt-0.5">{error}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
