import { useEffect, useRef, useCallback } from 'react'
import { message } from 'antd'

type AlertLevel = 'info' | 'warning' | 'critical'

interface WebSocketMessage {
  type: 'new_alert' | 'alert_resolved' | 'heartbeat' | 'pong'
  alert?: {
    id: string
    metric: string
    message: string
    level: AlertLevel
    created_at: string
  }
  message?: string
  level?: AlertLevel
  timestamp: string
  active_alerts?: number
}

interface UseWebSocketOptions {
  onNewAlert?: (alert: WebSocketMessage['alert']) => void
  onAlertResolved?: () => void
  enabled?: boolean
}

/**
 * WebSocket 自定义 Hook
 *
 * @param options 配置选项
 * @returns 连接状态
 */
export const useAlertWebSocket = (options: UseWebSocketOptions = {}) => {
  const { onNewAlert, onAlertResolved, enabled = true } = options
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const heartbeatIntervalRef = useRef<number | null>(null)

  const connect = useCallback(() => {
    if (!enabled) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws/alerts`

    try {
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('WebSocket 连接已建立')
        // 启动心跳
        heartbeatIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, 30000) // 30 秒心跳
      }

      ws.onmessage = (event) => {
        try {
          const data: WebSocketMessage = JSON.parse(event.data)

          switch (data.type) {
            case 'new_alert':
              console.log('收到新告警:', data.alert)
              // 显示通知
              const levelMap = {
                info: 'info',
                warning: 'warning',
                critical: 'error',
              }
              message[levelMap[data.level || 'warning']](
                data.message || '新告警通知'
              )
              // 回调
              if (onNewAlert && data.alert) {
                onNewAlert(data.alert)
              }
              break

            case 'alert_resolved':
              console.log('告警已解决')
              message.success(data.message || '有告警已被解决')
              if (onAlertResolved) {
                onAlertResolved()
              }
              break

            case 'heartbeat':
              // 心跳响应，可以在 UI 上显示连接状态
              break

            case 'pong':
              // 心跳确认
              break

            default:
              console.warn('未知的 WebSocket 消息类型:', data.type)
          }
        } catch (error) {
          console.error('解析 WebSocket 消息失败:', error)
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket 错误:', error)
      }

      ws.onclose = () => {
        console.log('WebSocket 连接已关闭，尝试重连...')
        // 清除心跳
        if (heartbeatIntervalRef.current) {
          clearInterval(heartbeatIntervalRef.current)
        }
        // 5 秒后重连
        reconnectTimeoutRef.current = setTimeout(() => {
          connect()
        }, 5000)
      }

      wsRef.current = ws
    } catch (error) {
      console.error('创建 WebSocket 连接失败:', error)
      // 5 秒后重试
      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, 5000)
    }
  }, [enabled, onNewAlert, onAlertResolved])

  // 断开连接
  const disconnect = useCallback(() => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current)
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    // 初始连接
    connect()

    // 清理
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  return {
    connected: wsRef.current?.readyState === WebSocket.OPEN,
  }
}
