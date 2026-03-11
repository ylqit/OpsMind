import { useEffect, useRef, useState } from 'react'

interface TaskEventMessage {
  type: string
  task_id?: string
  task_type?: string
  status?: string
  current_stage?: string
  progress?: number
  progress_message?: string
  updated_at?: string
  [key: string]: unknown
}

interface UseTaskEventStreamOptions {
  enabled?: boolean
  onEvent?: (event: TaskEventMessage) => void
}

export const useTaskEventStream = (options: UseTaskEventStreamOptions = {}) => {
  const { enabled = true, onEvent } = options
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const heartbeatTimerRef = useRef<number | null>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!enabled) {
      return undefined
    }

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${window.location.host}/api/ws/events`
      const socket = new WebSocket(url)

      socket.onopen = () => {
        setConnected(true)
        heartbeatTimerRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send('ping')
          }
        }, 30000)
      }

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as TaskEventMessage
          if (payload.type !== 'pong') {
            onEvent?.(payload)
          }
        } catch (error) {
          console.error('解析任务事件失败', error)
        }
      }

      socket.onclose = () => {
        setConnected(false)
        if (heartbeatTimerRef.current) {
          window.clearInterval(heartbeatTimerRef.current)
          heartbeatTimerRef.current = null
        }
        reconnectTimerRef.current = window.setTimeout(connect, 5000)
      }

      socket.onerror = () => {
        socket.close()
      }

      socketRef.current = socket
    }

    connect()

    return () => {
      if (heartbeatTimerRef.current) {
        window.clearInterval(heartbeatTimerRef.current)
      }
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current)
      }
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [enabled, onEvent])

  return { connected }
}
