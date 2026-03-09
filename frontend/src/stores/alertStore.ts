import { create } from 'zustand'
import { alertsApi, remediationApi } from '@/api/client'

interface Alert {
  id: string
  level: string
  metric: string
  message: string
  suggestion: string
  created_at: string
  status: string
  severity: string
}

interface AlertRule {
  id: string
  name: string
  metric: string
  threshold: number
  operator: string
  severity: string
  enabled: boolean
}

interface RemediationPlan {
  plan_id: string
  name: string
  description: string
  risk_level: string
  steps?: Array<{
    order: number
    name: string
    action: string
    command?: string
    description: string
    risk: string
    rollback?: string
  }>
}

interface AlertState {
  // 告警列表
  alerts: Alert[]
  alertsLoading: boolean
  alertsError: string | null

  // 告警规则
  rules: AlertRule[]
  rulesLoading: boolean

  // 修复预案
  plans: RemediationPlan[]
  selectedPlan: RemediationPlan | null

  // 动作
  fetchAlerts: (status?: string, severity?: string) => Promise<void>
  acknowledgeAlert: (alertId: string) => Promise<void>
  resolveAlert: (alertId: string) => Promise<void>
  fetchRules: () => Promise<void>
  createRule: (ruleData: Partial<AlertRule>) => Promise<void>
  deleteRule: (ruleId: string) => Promise<void>
  fetchPlans: () => Promise<void>
  getPlan: (planId: string) => Promise<void>
  executePlan: (planId: string, stepIndices: number[], dryRun: boolean, containerName?: string) => Promise<any>
}

export const useAlertStore = create<AlertState>((set, get) => ({
  // 初始状态
  alerts: [],
  alertsLoading: false,
  alertsError: null,

  rules: [],
  rulesLoading: false,

  plans: [],
  selectedPlan: null,

  // 获取告警列表
  fetchAlerts: async (status?: string, severity?: string) => {
    set({ alertsLoading: true, alertsError: null })
    try {
      const data = await alertsApi.query(status, severity, 50)
      set({ alerts: data.alerts || [], alertsLoading: false })
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取告警列表失败'
      set({ alertsError: message, alertsLoading: false })
    }
  },

  // 确认告警
  acknowledgeAlert: async (alertId: string) => {
    try {
      await alertsApi.acknowledge(alertId)
      // 刷新列表
      await get().fetchAlerts()
    } catch (error) {
      console.error('确认告警失败:', error)
      throw error
    }
  },

  // 解决告警
  resolveAlert: async (alertId: string) => {
    try {
      await alertsApi.resolve(alertId)
      // 刷新列表
      await get().fetchAlerts()
    } catch (error) {
      console.error('解决告警失败:', error)
      throw error
    }
  },

  // 获取告警规则
  fetchRules: async () => {
    set({ rulesLoading: true })
    try {
      const data = await alertsApi.listRules()
      set({ rules: data.rules || [], rulesLoading: false })
    } catch (error) {
      set({ rulesLoading: false })
      console.error('获取规则失败:', error)
    }
  },

  // 创建告警规则
  createRule: async (ruleData: Partial<AlertRule>) => {
    await alertsApi.createRule(ruleData)
    await get().fetchRules()
  },

  // 删除告警规则
  deleteRule: async (ruleId: string) => {
    await alertsApi.deleteRule(ruleId)
    await get().fetchRules()
  },

  // 获取修复预案列表
  fetchPlans: async () => {
    try {
      const data = await remediationApi.listPlans()
      set({ plans: data })
    } catch (error) {
      console.error('获取预案列表失败:', error)
    }
  },

  // 获取预案详情
  getPlan: async (planId: string) => {
    try {
      const data = await remediationApi.getPlan(planId)
      set({ selectedPlan: data })
      return data
    } catch (error) {
      console.error('获取预案详情失败:', error)
      throw error
    }
  },

  // 执行修复预案
  executePlan: async (planId: string, stepIndices: number[], dryRun: boolean, containerName?: string) => {
    return await remediationApi.execute(planId, stepIndices, dryRun, containerName)
  },
}))
