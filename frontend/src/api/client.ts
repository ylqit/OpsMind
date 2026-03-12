import axios from 'axios'
import { getErrorMessage, getErrorType } from '../utils/errorHandler'

const API_BASE_URL = '/api'

export interface OverviewCard {
  key: string
  label: string
  value: number | string
  unit?: string
  status: 'normal' | 'warning' | 'critical' | 'info'
}

export interface TimeSeriesPoint {
  timestamp: string
  value: number
}

export interface IncidentRecord {
  incident_id: string
  title: string
  severity: string
  status: string
  service_key: string
  summary: string
  confidence: number
  reasoning_tags: string[]
  recommended_actions: string[]
  evidence_refs: Array<Record<string, unknown>>
  related_asset_ids: string[]
  time_window_start: string
  time_window_end: string
  created_at: string
  updated_at: string
}

export interface TaskArtifact {
  artifact_id: string
  task_id: string
  kind: string
  path: string
  preview: string
  size_bytes: number
  created_at: string
}

export interface RecommendationRecord {
  recommendation_id: string
  incident_id: string
  target_asset_id?: string | null
  kind: string
  confidence: number
  observation: string
  recommendation: string
  risk_note: string
  artifact_refs: TaskArtifact[]
  created_at: string
  updated_at: string
}

export interface TaskApproval {
  approved_by: string
  approval_note: string
  approved_at: string
}

export interface TaskRecord {
  task_id: string
  task_type: string
  status: string
  current_stage: string
  progress: number
  progress_message: string
  trace_id: string
  payload: Record<string, unknown>
  result_ref?: Record<string, unknown> | null
  error?: {
    error_code: string
    error_message: string
    failed_stage?: string | null
  } | null
  approval?: TaskApproval | null
  created_at: string
  updated_at: string
  completed_at?: string | null
}

export interface DashboardOverview {
  cards: OverviewCard[]
  traffic_trend: TimeSeriesPoint[]
  recent_incidents: IncidentRecord[]
  hot_services: Array<{
    service_key: string
    score: number
    reason: string
    metric_value: number
  }>
  data_sources: Record<string, unknown>
}

export interface TrafficErrorSample {
  timestamp: string
  method: string
  path: string
  status: number
  latency_ms: number
  client_ip: string
  geo_label: string
  browser: string
  os: string
  device: string
}

export interface TrafficSummary {
  total_requests: number
  page_views: number
  error_rate: number
  avg_latency: number
  top_paths: Array<{ path: string; count: number }>
  hot_paths: Array<{ path: string; count: number; error_count: number; error_rate: number; avg_latency: number }>
  top_ips: Array<{ ip: string; count: number }>
  hot_ips: Array<{ ip: string; count: number; error_count: number; error_rate: number; avg_latency: number; sample_path: string; geo_label: string }>
  status_distribution: Array<{ status: string; count: number }>
  geo_distribution: Array<{ name: string; count: number }>
  ua_distribution: Array<{ name: string; count: number }>
  trend: Array<{ timestamp: string; requests: number; errors: number }>
  error_samples: TrafficErrorSample[]
  records_sample?: Array<Record<string, unknown>>
}

export interface ResourceSummary {
  host: Record<string, any>
  alerts: Array<Record<string, unknown>>
  containers: {
    available: boolean
    items: Array<Record<string, any>>
  }
  prometheus: {
    available: boolean
    metrics: Record<string, unknown>
  }
  hotspots: Array<{ name: string; type: string; score: number; reason: string }>
}

export interface TaskDetailResponse {
  task: TaskRecord
  trace_preview: Array<Record<string, unknown>>
  artifacts: TaskArtifact[]
}

export interface IncidentLogSample {
  timestamp: string
  method: string
  path: string
  status: number
  latency_ms: number
  client_ip: string
  geo_label: string
  user_agent: string
  browser: string
  os: string
  device: string
  service_key: string
}

export interface IncidentDetailResponse {
  incident: IncidentRecord
  recommendations: RecommendationRecord[]
  log_samples: IncidentLogSample[]
}

export interface ArtifactContentResponse {
  artifact: TaskArtifact
  filename: string
  content: string
  content_type: string
}

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

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
      if (status === 401) {
        throw new Error('未授权访问')
      }
      if (status === 403) {
        throw new Error('无权访问')
      }
    }
    if (!error.response && error.message) {
      const type = getErrorType(error)
      throw new Error(getErrorMessage(error, type))
    }
    throw error
  },
)

export const capabilitiesApi = {
  list: () => apiClient.get('/capabilities'),
  getSchema: (name: string) => apiClient.get(`/capabilities/${name}/schema`),
  dispatch: (name: string, params: Record<string, unknown>) => apiClient.post(`/capabilities/${name}/dispatch`, { params }),
}

export const alertsApi = {
  query: (status?: string, severity?: string, limit?: number) => apiClient.get('/alerts', { params: { status, severity, limit } }),
  acknowledge: (alertId: string, acknowledgedBy?: string) =>
    apiClient.post('/alerts/acknowledge', null, {
      params: { alert_id: alertId, acknowledged_by: acknowledgedBy || 'user' },
    }),
  resolve: (alertId: string, resolvedBy?: string) =>
    apiClient.post('/alerts/resolve', null, {
      params: { alert_id: alertId, resolved_by: resolvedBy || 'user' },
    }),
  createRule: (ruleData: Record<string, unknown>) => apiClient.post('/alerts/rules', ruleData),
  listRules: () => apiClient.get('/alerts/rules'),
  deleteRule: (ruleId: string) => apiClient.delete(`/alerts/rules/${ruleId}`),
}

export const remediationApi = {
  listPlans: () => apiClient.get('/remediation/plans'),
  getPlan: (planId: string) => apiClient.get(`/remediation/plans/${planId}`),
  execute: (planId: string, stepIndices: number[], dryRun?: boolean, containerName?: string) =>
    apiClient.post('/remediation/execute', null, {
      params: {
        plan_id: planId,
        step_indices: stepIndices,
        dry_run: dryRun ?? true,
        container_name: containerName,
      },
    }),
}

export const containersApi = {
  list: () => apiClient.get('/containers'),
  get: (name: string) => apiClient.get(`/containers/${name}`),
  getLogs: (name: string, lines?: number) => apiClient.get(`/containers/${name}/logs`, { params: { lines: lines ?? 50 } }),
}

export const hostApi = {
  getMetrics: () => apiClient.get('/host/metrics'),
}

export const dashboardApi = {
  getOverview: (params?: { time_range?: string; service_key?: string }) => apiClient.get('/dashboard/overview', { params }),
  createDailyReport: (payload: { date: string; scope: string }) => apiClient.post('/reports/daily', payload),
}

export const trafficApi = {
  getSummary: (params?: { time_range?: string; service_key?: string; asset_id?: string }) => apiClient.get('/traffic/summary', { params }),
}

export const resourcesApi = {
  getSummary: (params?: { time_range?: string; service_key?: string; asset_id?: string }) => apiClient.get('/resources/summary', { params }),
  listAssets: (params?: { asset_type?: string; service_key?: string; health_status?: string }) => apiClient.get('/assets', { params }),
}

export const incidentsApi = {
  list: (params?: { status?: string; severity?: string; service_key?: string; time_range?: string }) => apiClient.get('/incidents', { params }),
  get: (incidentId: string) => apiClient.get(`/incidents/${incidentId}`),
  analyze: (payload: { service_key?: string; asset_id?: string; time_window: string }) => apiClient.post('/incidents/analyze', payload),
}

export const recommendationsApi = {
  get: (recommendationId: string) => apiClient.get(`/recommendations/${recommendationId}`),
  generate: (payload: { incident_id: string; kinds?: string[] }) => apiClient.post('/recommendations/generate', payload),
}

export const tasksApi = {
  list: (params?: { task_type?: string; status?: string }) => apiClient.get('/tasks', { params }),
  get: (taskId: string) => apiClient.get(`/tasks/${taskId}`),
  approve: (taskId: string, payload?: { approved_by?: string; approval_note?: string }) => apiClient.post(`/tasks/${taskId}/approve`, payload),
  cancel: (taskId: string) => apiClient.post(`/tasks/${taskId}/cancel`),
  getArtifact: (taskId: string, artifactId: string) => apiClient.get(`/tasks/${taskId}/artifacts/${artifactId}`),
  getArtifactContent: (taskId: string, artifactId: string) => apiClient.get(`/tasks/${taskId}/artifacts/${artifactId}/content`),
  getArtifactDownloadUrl: (taskId: string, artifactId: string) => `${API_BASE_URL}/tasks/${taskId}/artifacts/${artifactId}/download`,
}

export default apiClient
