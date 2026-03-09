import axios from 'axios'

const API_BASE_URL = '/api'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      if (status === 404) {
        throw new Error(data.detail || '资源不存在')
      }
      if (status === 500) {
        throw new Error(data.detail || '服务器内部错误')
      }
    }
    throw error
  }
)

// 能力相关 API
export const capabilitiesApi = {
  // 获取所有能力列表
  list: () => apiClient.get('/capabilities'),

  // 获取能力 schema
  getSchema: (name: string) => apiClient.get(`/capabilities/${name}/schema`),

  // 调用能力
  dispatch: (name: string, params: Record<string, any>) =>
    apiClient.post(`/capabilities/${name}/dispatch`, { params }),
}

// 告警相关 API
export const alertsApi = {
  // 查询告警列表
  query: (status?: string, severity?: string, limit?: number) =>
    apiClient.get('/alerts', { params: { status, severity, limit } }),

  // 确认告警
  acknowledge: (alertId: string, acknowledgedBy?: string) =>
    apiClient.post('/alerts/acknowledge', null, {
      params: { alert_id: alertId, acknowledged_by: acknowledgedBy || 'user' },
    }),

  // 解决告警
  resolve: (alertId: string, resolvedBy?: string) =>
    apiClient.post('/alerts/resolve', null, {
      params: { alert_id: alertId, resolved_by: resolvedBy || 'user' },
    }),

  // 创建告警规则
  createRule: (ruleData: Record<string, any>) =>
    apiClient.post('/alerts/rules', ruleData),

  // 获取告警规则列表
  listRules: () => apiClient.get('/alerts/rules'),

  // 删除告警规则
  deleteRule: (ruleId: string) =>
    apiClient.delete(`/alerts/rules/${ruleId}`),
}

// 修复预案相关 API
export const remediationApi = {
  // 获取所有预案列表
  listPlans: () => apiClient.get('/remediation/plans'),

  // 获取预案详情
  getPlan: (planId: string) =>
    apiClient.get(`/remediation/plans/${planId}`),

  // 执行修复
  execute: (
    planId: string,
    stepIndices: number[],
    dryRun?: boolean,
    containerName?: string
  ) =>
    apiClient.post('/remediation/execute', null, {
      params: {
        plan_id: planId,
        step_indices: stepIndices,
        dry_run: dryRun ?? true,
        container_name: containerName,
      },
    }),
}

// 容器相关 API
export const containersApi = {
  // 获取容器列表
  list: () => apiClient.get('/containers'),

  // 获取容器详情
  get: (name: string) => apiClient.get(`/containers/${name}`),

  // 获取容器日志
  getLogs: (name: string, lines?: number) =>
    apiClient.get(`/containers/${name}/logs`, {
      params: { lines: lines ?? 50 },
    }),
}

// 主机监控相关 API
export const hostApi = {
  // 获取主机指标
  getMetrics: () => apiClient.get('/host/metrics'),
}
