import { create } from 'zustand'
import { hostApi, containersApi } from '@/api/client'

interface HostMetrics {
  cpu?: {
    usage_percent: number
    cpu_count: number
    cpu_freq?: {
      current: number
      min: number
      max: number
    }
    load_avg?: [number, number, number]
  }
  memory?: {
    total_mb: number
    available_mb: number
    usage_percent: number
    used_mb: number
    swap_total_mb: number
    swap_usage_percent: number
  }
  disk?: {
    partitions: Array<{
      device: string
      mountpoint: string
      fstype: string
      total_gb: number
      used_gb: number
      usage_percent: number
      free_gb: number
    }>
  }
  network?: {
    bytes_sent_mb: number
    bytes_recv_mb: number
    packets_sent: number
    packets_recv: number
    interfaces: Record<string, string[]>
  }
  alerts?: Array<{
    level: string
    metric: string
    message: string
    suggestion: string
  }>
}

interface Container {
  id: string
  name: string
  image: string
  status: string
  state: string
}

interface MonitorState {
  // 主机指标
  hostMetrics: HostMetrics | null
  hostLoading: boolean
  hostError: string | null

  // 容器列表
  containers: Container[]
  containersLoading: boolean
  containersError: string | null

  // 动作
  fetchHostMetrics: () => Promise<void>
  fetchContainers: () => Promise<void>
  refreshAll: () => Promise<void>
}

export const useMonitorStore = create<MonitorState>((set, get) => ({
  // 初始状态
  hostMetrics: null,
  hostLoading: false,
  hostError: null,

  containers: [],
  containersLoading: false,
  containersError: null,

  // 获取主机指标
  fetchHostMetrics: async () => {
    set({ hostLoading: true, hostError: null })
    try {
      const data = await hostApi.getMetrics()
      set({ hostMetrics: data, hostLoading: false })
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取主机指标失败'
      set({ hostError: message, hostLoading: false })
    }
  },

  // 获取容器列表
  fetchContainers: async () => {
    set({ containersLoading: true, containersError: null })
    try {
      const data = await containersApi.list()
      set({ containers: data.containers || [], containersLoading: false })
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取容器列表失败'
      set({ containersError: message, containersLoading: false })
    }
  },

  // 刷新所有数据
  refreshAll: async () => {
    await Promise.all([
      get().fetchHostMetrics(),
      get().fetchContainers(),
    ])
  },
}))
