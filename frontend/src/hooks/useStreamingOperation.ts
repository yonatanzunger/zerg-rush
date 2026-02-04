import { useState, useCallback, useRef } from 'react'
import type { Agent } from '../types'

/**
 * Event types from the server streaming endpoint
 */
export interface StreamEvent {
  type: 'log' | 'span_start' | 'span_end' | 'complete' | 'error'
  timestamp: string
  message: string
  depth?: number
  data?: Record<string, unknown>
  duration_ms?: number
}

/**
 * Result of a streaming operation
 */
export interface StreamingOperationResult<T = Agent> {
  /** All events received during the operation */
  events: StreamEvent[]
  /** Whether the operation is currently in progress */
  isLoading: boolean
  /** Error message if the operation failed */
  error: string | null
  /** The result data (e.g., created agent) if operation completed successfully */
  result: T | null
  /** Execute a streaming POST request */
  executePost: (url: string, body?: unknown) => Promise<T | null>
  /** Execute a streaming DELETE request */
  executeDelete: (url: string) => Promise<boolean>
  /** Clear all events and reset state */
  reset: () => void
}

/**
 * Hook for executing long-running operations with streaming progress updates.
 *
 * The server sends Server-Sent Events (SSE) with progress updates during
 * operations like VM creation, deletion, start, and stop.
 *
 * @example
 * ```tsx
 * const { events, isLoading, error, result, executePost } = useStreamingOperation<Agent>()
 *
 * const handleCreate = async () => {
 *   const agent = await executePost('/api/agents/stream', { name: 'My Agent' })
 *   if (agent) {
 *     console.log('Created agent:', agent.id)
 *   }
 * }
 * ```
 */
export function useStreamingOperation<T = Agent>(): StreamingOperationResult<T> {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<T | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const reset = useCallback(() => {
    setEvents([])
    setError(null)
    setResult(null)
    setIsLoading(false)
  }, [])

  const executeStream = useCallback(
    async (url: string, method: 'POST' | 'DELETE', body?: unknown): Promise<T | null> => {
      // Abort any existing operation
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }

      const abortController = new AbortController()
      abortControllerRef.current = abortController

      setIsLoading(true)
      setEvents([])
      setError(null)
      setResult(null)

      const token = localStorage.getItem('token')

      try {
        const response = await fetch(url, {
          method,
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: body ? JSON.stringify(body) : undefined,
          signal: abortController.signal,
        })

        if (!response.ok) {
          const errorText = await response.text()
          let errorMessage = `Request failed: ${response.status}`
          try {
            const errorJson = JSON.parse(errorText)
            errorMessage = errorJson.detail || errorMessage
          } catch {
            // Use default error message
          }
          throw new Error(errorMessage)
        }

        if (!response.body) {
          throw new Error('No response body')
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let finalResult: T | null = null

        while (true) {
          const { done, value } = await reader.read()

          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })

          // Process complete SSE messages
          const lines = buffer.split('\n')
          buffer = lines.pop() || '' // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event: StreamEvent = JSON.parse(line.slice(6))

                if (event.type === 'error') {
                  setError(event.message)
                } else if (event.type === 'complete') {
                  // Extract result from the complete event
                  if (event.data?.agent) {
                    finalResult = event.data.agent as T
                    setResult(finalResult)
                  }
                  // Add the completion event to the list
                  setEvents((prev) => [...prev, event])
                } else {
                  // Add log/span events to the list
                  setEvents((prev) => [...prev, event])
                }
              } catch (parseError) {
                console.error('Failed to parse SSE event:', line, parseError)
              }
            }
          }
        }

        return finalResult
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Operation was cancelled
          return null
        }
        const errorMessage = err instanceof Error ? err.message : 'Unknown error'
        setError(errorMessage)
        return null
      } finally {
        setIsLoading(false)
        abortControllerRef.current = null
      }
    },
    []
  )

  const executePost = useCallback(
    (url: string, body?: unknown) => executeStream(url, 'POST', body),
    [executeStream]
  )

  const executeDelete = useCallback(
    async (url: string): Promise<boolean> => {
      await executeStream(url, 'DELETE')
      // For delete operations, success is indicated by no error
      return error === null && !isLoading
    },
    [executeStream, error, isLoading]
  )

  return {
    events,
    isLoading,
    error,
    result,
    executePost,
    executeDelete,
    reset,
  }
}

export default useStreamingOperation
