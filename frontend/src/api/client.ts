import axios from 'axios'
import { getErrorMessage, getErrorType } from '@/utils/errorHandler'

const API_BASE_URL = '/api'

const encodePathSegment = (value: string) => encodeURIComponent(value)

const buildTaskArtifactPath = (taskId: string, artifactId: string) =>
  `/tasks/${encodePathSegment(taskId)}/artifacts/${encodePathSegment(artifactId)}`

// 兼容 FastAPI 常见 detail 结构，避免 detail 为对象或数组时前端提示失真。
const extractErrorDetail = (payload: unknown): string => {
  if (typeof payload === 'string') {
    return payload
  }
  if (!payload || typeof payload !== 'object') {
    return ''
  }
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') {
          return item
        }
        if (!item || typeof item !== 'object') {
          return ''
        }
        const message = (item as { msg?: unknown }).msg
        return typeof message === 'string' ? message : ''
      })
      .filter(Boolean)
      .join('；')
  }
  return ''
}

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
  evidence_refs: IncidentEvidenceRef[]
  related_asset_ids: string[]
  time_window_start: string
  time_window_end: string
  created_at: string
  updated_at: string
}

export interface IncidentEvidenceRef {
  evidence_id: string
  layer: string
  type: string
  source_type: string
  title: string
  summary: string
  metric: string
  value?: unknown
  unit?: string
  priority: number
  signal_strength: 'high' | 'medium' | 'low'
  source_ref: {
    service_key?: string
    asset_ids?: string[]
    task_id?: string
    trace_id?: string
    alert_id?: string
    timestamp?: string
    path?: string
    status?: string | number
    source?: string
    namespace?: string
    client_ip?: string
    geo_label?: string
    layer?: string
    [key: string]: unknown
  }
  tags: string[]
  next_step?: string
  reasoning_tags?: string[]
  alignment?: Record<string, unknown>
  service_key?: string
  current_stage?: string
  progress?: number
  severity?: string
  [key: string]: unknown
}

export interface IncidentEvidenceSummary {
  total: number
  layers: Record<string, number>
  primary_layer: string
  headline: string
  next_step: string
  reasoning_tags: string[]
  highlights: IncidentEvidenceRef[]
  summary_lines: string[]
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

export interface RecommendationEvidenceRef {
  evidence_id: string
  source_type: 'artifact' | 'log_snippet' | 'metric_snapshot' | 'incident_evidence'
  title: string
  summary: string
  quote: string
  metric?: string
  priority?: number
  signal_strength?: string
  artifact_ref?: TaskArtifact | null
  jump?: {
    kind: 'artifact' | 'none'
    task_id?: string
    artifact_id?: string
  }
}

export type RecommendationArtifactViewKey = 'baseline' | 'recommended' | 'diff'

export interface RecommendationArtifactView {
  view_key: RecommendationArtifactViewKey
  label: string
  filename: string
  kind: string
  artifact_id: string
  task_id: string
  summary: string
  line_count?: number
  document_count?: number
  sha256?: string
  from_filename?: string
  to_filename?: string
  added_lines?: number
  removed_lines?: number
  hunk_count?: number
  total_changed_lines?: number
  change_level?: 'high' | 'medium' | 'low' | string
  risk_level?: 'high' | 'medium' | 'low' | string
  resource_types?: Array<{ kind: string; count: number }>
}

export interface RecommendationRiskSummary {
  level: 'high' | 'medium' | 'low' | string
  score: number
  review_required: boolean
  highlights: string[]
}

export interface RecommendationResourceHints {
  baseline_types: Array<{ kind: string; count: number }>
  recommended_types: Array<{ kind: string; count: number }>
  added_types: string[]
  removed_types: string[]
}

export interface RecommendationChangeStats {
  total_changed_lines: number
  change_level: 'high' | 'medium' | 'low' | string
  added_lines: number
  removed_lines: number
  hunk_count: number
}

export interface RecommendationArtifactViewsPayload {
  primary_view: RecommendationArtifactViewKey | null
  available_views: RecommendationArtifactViewKey[]
  baseline?: RecommendationArtifactView | null
  recommended?: RecommendationArtifactView | null
  diff?: RecommendationArtifactView | null
  risk_summary?: RecommendationRiskSummary | null
  resource_hints?: RecommendationResourceHints | null
  change_stats?: RecommendationChangeStats | null
}

export interface RecommendationDetailResponse extends RecommendationRecord {
  evidence_refs: RecommendationEvidenceRef[]
  log_samples: LogSampleRecord[]
  evidence_status: 'sufficient' | 'insufficient'
  evidence_message: string
  confidence_effective: number
  recommendation_effective: string
  evidence_summary: {
    total: number
    artifact: number
    log_snippet: number
    metric_snapshot: number
    incident_evidence?: number
  }
  artifact_views?: RecommendationArtifactViewsPayload
  feedback_summary?: {
    adopt: number
    reject: number
    rewrite: number
  }
  feedback_items?: RecommendationFeedbackRecord[]
  task_context?: {
    task_id: string
    task_type: string
    status: string
    current_stage: string
    progress: number
    progress_message: string
    created_at: string
    updated_at: string
    completed_at?: string | null
    approval?: TaskApproval | null
  } | null
  task_trace_preview?: Array<Record<string, unknown>>
  task_trace_summary?: {
    total_steps: number
    last_step: {
      step: string
      action: string
      stage: string
      summary: string
      created_at: string
    } | null
  }
}

export type RecommendationFeedbackAction = 'adopt' | 'reject' | 'rewrite'

export interface RecommendationFeedbackRecord {
  feedback_id: string
  recommendation_id: string
  incident_id: string
  task_id?: string | null
  action: RecommendationFeedbackAction
  reason_code: string
  comment: string
  operator: string
  created_at: string
}

export interface RecommendationFeedbackListResponse {
  recommendation_id: string
  summary: {
    adopt: number
    reject: number
    rewrite: number
  }
  items: RecommendationFeedbackRecord[]
}

export interface RecommendationFeedbackSaveResponse {
  item: RecommendationFeedbackRecord
  summary: {
    adopt: number
    reject: number
    rewrite: number
  }
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

export interface IncidentRecommendationTaskLink extends TaskRecord {
  artifact_ready: boolean
  artifact_count: number
  recommendation_count: number
  recommendation_ids: string[]
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
  data_health: {
    status: 'ready' | 'degraded' | 'unavailable'
    title: string
    message: string
    degradation_reasons: string[]
  }
  data_sources: Record<string, DataSourceHealthItem>
}

export interface DataSourceHealthItem {
  enabled?: boolean
  configured?: boolean
  available?: boolean
  status?: 'ready' | 'empty' | 'degraded' | 'unavailable' | 'not_configured' | string
  message?: string
  details?: Record<string, unknown>
  [key: string]: unknown
}

export interface LogSampleRecord {
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

export type TrafficErrorSample = LogSampleRecord

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
  error_samples: LogSampleRecord[]
  records_sample?: Array<Record<string, unknown>>
  data_status?: 'ready' | 'empty' | 'degraded' | 'unavailable'
  data_message?: string
  degradation_reasons?: string[]
  load_stats?: {
    configured_paths: number
    scanned_files: number
    missing_files: number
    unreadable_files: number
    lines_read: number
    parsed_lines: number
    matched_records: number
    parse_failures: number
    enrich_failures: number
    time_filtered: number
    service_filtered: number
  }
}

export interface ResourceHotspot {
  name: string
  type: string
  layer: string
  score: number
  severity: 'critical' | 'high' | 'medium'
  category: 'cpu' | 'memory' | 'restart' | 'oom' | 'status' | 'disk' | 'network' | 'other'
  reason: string
  explanation: string
  recommended_action: string
  metric: string
  value: string | number
  unit?: string
  source?: string
  labels?: string[]
  service_key?: string
  namespace?: string
}

export interface ResourceHotspotLayers {
  host: ResourceHotspot[]
  container: ResourceHotspot[]
  pod: ResourceHotspot[]
  service: ResourceHotspot[]
  other: ResourceHotspot[]
}

export type ResourceRiskLevel = 'critical' | 'high' | 'medium'
export type ResourceRiskType = 'oom' | 'restart'

export interface ResourceRiskBucket {
  total: number
  critical: number
  high: number
  medium: number
}

export interface ResourceRiskSummary {
  total: number
  levels: {
    critical: number
    high: number
    medium: number
  }
  oom: ResourceRiskBucket
  restart: ResourceRiskBucket
}

export interface ResourceRiskItem {
  risk_id: string
  risk_type: ResourceRiskType
  level: ResourceRiskLevel
  layer: string
  target: string
  service_key: string
  metric: string
  value: string | number
  unit?: string
  evidence: string
  source: string
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
  hotspots: ResourceHotspot[]
  hotspot_layers: ResourceHotspotLayers
  hotspot_summary: {
    total: number
    layers: Record<string, number>
    severities: {
      critical: number
      high: number
      medium: number
    }
    categories: Record<string, number>
    top_services: Array<{
      service_key: string
      count: number
      top_score: number
    }>
  }
  risk_summary: ResourceRiskSummary
  risk_items: ResourceRiskItem[]
  source_health: Record<string, DataSourceHealthItem>
  data_status: 'ready' | 'degraded' | 'unavailable'
  data_message: string
  degradation_reasons: string[]
}

export interface TaskFailureDiagnosis {
  task_id: string
  status: string
  retryable: boolean
  error: {
    error_code: string
    error_message: string
    failed_stage: string
  }
  trace_stats: {
    total_steps: number
    stages: Record<string, number>
    last_step: {
      step: string
      action: string
      stage: string
      summary: string
      created_at: string
    } | null
  }
  artifact_count: number
  artifact_hints: string[]
  possible_causes: string[]
  suggested_actions: string[]
}

export interface TaskArtifactGroup {
  group_key: string
  count: number
  items: TaskArtifact[]
}

export interface TaskArtifactListResponse {
  items: TaskArtifact[]
  total: number
  filtered: number
  kind: string
  query: string
  group_by: string
  groups: TaskArtifactGroup[]
}

export interface TaskDetailResponse {
  task: TaskRecord
  trace_preview: Array<Record<string, unknown>>
  artifacts: TaskArtifact[]
  failure_diagnosis?: TaskFailureDiagnosis | null
}

export type IncidentLogSample = LogSampleRecord

export interface IncidentDetailResponse {
  incident: IncidentRecord
  recommendations: RecommendationRecord[]
  log_samples: LogSampleRecord[]
  evidence_summary: IncidentEvidenceSummary
  recommendation_task?: IncidentRecommendationTaskLink | null
  recommendation_tasks?: IncidentRecommendationTaskLink[]
}

export interface AISummaryRoleView {
  headline: string
  key_findings: string[]
  actions: string[]
}

export interface AISummaryRoleViews {
  traffic?: AISummaryRoleView
  resource?: AISummaryRoleView
  risk?: AISummaryRoleView
}

export interface IncidentAISummaryResponse {
  incident_id: string
  provider: string
  summary: string
  risk_level: 'high' | 'medium' | 'low'
  confidence: number
  primary_causes: string[]
  recommended_actions: string[]
  evidence_citations: string[]
  role_views?: AISummaryRoleViews
  parse_mode: string
  validation_status?: string
  retry_count?: number
  guardrail_error_code?: string
  guardrail_error_message?: string
  log_sample_count: number
  recommendation_count: number
}

export interface RecommendationAIReviewResponse {
  recommendation_id: string
  incident_id: string
  provider: string
  summary: string
  risk_level: 'high' | 'medium' | 'low'
  confidence: number
  risk_assessment: string
  rollback_plan: string[]
  validation_checks: string[]
  evidence_citations: string[]
  role_views?: AISummaryRoleViews
  parse_mode: string
  validation_status?: string
  retry_count?: number
  guardrail_error_code?: string
  guardrail_error_message?: string
}

export interface RecommendationMetricsTrendItem {
  date: string
  feedback_total: number
  adopt: number
  reject: number
  rewrite: number
  adopt_rate: number
  reject_rate: number
  rewrite_rate: number
  feedback_bound_task: number
  feedback_unbound_task: number
  feedback_bound_rate: number
  task_total: number
  task_success: number
  task_failed: number
  task_approved: number
  task_approval_rate: number
  task_success_rate: number
  avg_task_duration_ms: number
}

export interface RecommendationMetricsServiceItem {
  service_key: string
  feedback_total: number
  adopt: number
  reject: number
  rewrite: number
  adopt_rate: number
  feedback_bound_task: number
  feedback_unbound_task: number
  feedback_bound_rate: number
  task_total: number
  task_success: number
  task_failed: number
  task_approved: number
  task_approval_rate: number
  task_success_rate: number
  avg_task_duration_ms: number
}

export interface RecommendationMetricsDimensionItem {
  provider_name?: string
  model?: string
  version?: string
  feedback_total: number
  adopt: number
  reject: number
  rewrite: number
  adopt_rate: number
  reject_rate: number
  rewrite_rate: number
  feedback_bound_task: number
  feedback_unbound_task: number
  feedback_bound_rate: number
  task_total: number
  task_success: number
  task_failed: number
  task_approved: number
  task_approval_rate: number
  task_success_rate: number
  avg_task_duration_ms: number
}

export interface RecommendationMetricsResponse {
  start_date: string
  end_date: string
  service_key: string
  provider_name: string
  model: string
  version: string
  summary: {
    feedback_total: number
    adopt: number
    reject: number
    rewrite: number
    adopt_rate: number
    reject_rate: number
    rewrite_rate: number
    feedback_bound_task: number
    feedback_unbound_task: number
    feedback_bound_rate: number
    task_total: number
    task_success: number
    task_failed: number
    task_approved: number
    task_approval_rate: number
    task_success_rate: number
    avg_task_duration_ms: number
  }
  trend: RecommendationMetricsTrendItem[]
  service_breakdown: RecommendationMetricsServiceItem[]
  provider_breakdown: RecommendationMetricsDimensionItem[]
  model_breakdown: RecommendationMetricsDimensionItem[]
  version_breakdown: RecommendationMetricsDimensionItem[]
}

export interface AIUsageMetricsTrendItem {
  date: string
  ai_call_total: number
  ai_error_count: number
  ai_success_count: number
  ai_timeout_count: number
  ai_error_rate: number
  ai_timeout_rate: number
  guardrail_fallback_count: number
  guardrail_retried_count: number
  guardrail_schema_error_count: number
  guardrail_fallback_rate: number
  guardrail_schema_error_rate: number
  ai_avg_latency_ms: number
  ai_total_tokens: number
  ai_total_cost: number
}

export interface AIUsageMetricsGroupItem {
  service_key?: string
  model?: string
  provider_name?: string
  version?: string
  ai_call_total: number
  ai_error_count: number
  ai_success_count: number
  ai_timeout_count: number
  ai_error_rate: number
  ai_timeout_rate: number
  guardrail_fallback_count: number
  guardrail_retried_count: number
  guardrail_schema_error_count: number
  guardrail_fallback_rate: number
  guardrail_schema_error_rate: number
  ai_avg_latency_ms: number
  ai_total_tokens: number
  ai_total_cost: number
}

export interface AIUsageMetricsResponse {
  start_date: string
  end_date: string
  service_key: string
  provider_name: string
  model: string
  version: string
  summary: {
    ai_call_total: number
    ai_error_count: number
    ai_success_count: number
    ai_timeout_count: number
    ai_error_rate: number
    ai_timeout_rate: number
    guardrail_fallback_count: number
    guardrail_retried_count: number
    guardrail_schema_error_count: number
    guardrail_fallback_rate: number
    guardrail_schema_error_rate: number
    ai_avg_latency_ms: number
    ai_total_tokens: number
    ai_total_cost: number
    ai_cost_per_call: number
  }
  trend: AIUsageMetricsTrendItem[]
  service_breakdown: AIUsageMetricsGroupItem[]
  model_breakdown: AIUsageMetricsGroupItem[]
  provider_breakdown: AIUsageMetricsGroupItem[]
  version_breakdown: AIUsageMetricsGroupItem[]
  records_count: number
}

export interface ArtifactContentResponse {
  artifact: TaskArtifact
  filename: string
  content: string
  content_type: string
}

export interface LLMProviderRecord {
  provider_id?: string
  name: string
  type: string
  model: string
  base_url?: string | null
  enabled: boolean
  is_default?: boolean
  timeout: number
  max_retries: number
  api_key_configured: boolean
}

export interface LLMCallLogRecord {
  call_id: string
  provider_name: string
  model: string
  source: string
  endpoint: string
  task_id?: string | null
  prompt_preview: string
  response_preview: string
  status: 'success' | 'error'
  error_code?: string
  error_message: string
  latency_ms: number
  request_tokens?: number | null
  response_tokens?: number | null
  created_at: string
}

export type ExecutorHealthStatus = 'healthy' | 'degraded' | 'disabled'
export type ExecutorRunStatus = 'success' | 'error' | 'timeout' | 'rejected' | 'circuit_open'

export interface ExecutorReadonlyCategory {
  category_key: string
  category_label: string
  count: number
}

export interface ExecutorReadonlyCommandPack {
  template_id: string
  category_key: string
  category_label: string
  title: string
  description: string
  command: string
}

export interface ExecutorPluginStatus {
  plugin_key: string
  display_name: string
  description: string
  enabled: boolean
  readonly_only: boolean
  write_enabled: boolean
  failure_count: number
  circuit_open_until: string | null
  circuit_remaining_seconds: number
  last_error: string
  health_status: ExecutorHealthStatus
  readonly_examples: string[]
  write_examples: string[]
  readonly_categories: ExecutorReadonlyCategory[]
  readonly_command_packs: ExecutorReadonlyCommandPack[]
  updated_at: string
}

export interface ExecutorAuditLog {
  execution_id: string
  task_id?: string | null
  plugin_key: string
  command: string
  readonly: boolean
  status: ExecutorRunStatus
  exit_code: number | null
  stdout_preview: string
  stderr_preview: string
  duration_ms: number
  error_code: string
  error_message: string
  operator: string
  approval_ticket: string
  created_at: string
}

export interface ExecutorStatusResponse {
  plugins: ExecutorPluginStatus[]
  recent_logs: ExecutorAuditLog[]
  summary: {
    total: number
    enabled: number
    degraded: number
  }
}

export interface ExecutorRunResponse {
  execution: ExecutorAuditLog
  plugin: ExecutorPluginStatus
  task_evidence?: {
    linked: boolean
    reason?: string
    message?: string
    task_id?: string
    artifact_id?: string
    execution_id?: string
  }
}

export interface ExecutorReadonlyCommandPackListResponse {
  items: Array<{
    plugin_key: string
    display_name: string
    readonly_categories: ExecutorReadonlyCategory[]
    readonly_command_packs: ExecutorReadonlyCommandPack[]
  }>
  total: number
}

type HttpClient = {
  get<T = any>(url: string, config?: unknown): Promise<T>
  post<T = any>(url: string, data?: unknown, config?: unknown): Promise<T>
  put<T = any>(url: string, data?: unknown, config?: unknown): Promise<T>
  patch<T = any>(url: string, data?: unknown, config?: unknown): Promise<T>
  delete<T = any>(url: string, config?: unknown): Promise<T>
}

const rawApiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

rawApiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      const detail = extractErrorDetail(data)
      if (status === 401) {
        throw new Error('未授权访问')
      }
      if (status === 403) {
        throw new Error('无权访问')
      }
      if (status === 404) {
        throw new Error(detail || '资源不存在')
      }
      if (status === 409) {
        throw new Error(detail || '请求冲突，请刷新后重试')
      }
      if (status === 400 || status === 422) {
        throw new Error(detail || '请求参数错误，请检查输入')
      }
      if (status >= 500) {
        throw new Error(detail || '服务器内部错误')
      }
      if (status >= 400) {
        throw new Error(detail || '请求失败，请稍后重试')
      }
    }
    if (!error.response && error.message) {
      const type = getErrorType(error)
      throw new Error(getErrorMessage(error, type))
    }
    throw error
  },
)

const apiClient = rawApiClient as unknown as HttpClient

export const capabilitiesApi = {
  list: () => apiClient.get('/capabilities'),
  getSchema: (name: string) => apiClient.get(`/capabilities/${encodePathSegment(name)}/schema`),
  dispatch: (name: string, params: Record<string, unknown>) => apiClient.post(`/capabilities/${encodePathSegment(name)}/dispatch`, { params }),
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
  deleteRule: (ruleId: string) => apiClient.delete(`/alerts/rules/${encodePathSegment(ruleId)}`),
}

export const remediationApi = {
  listPlans: () => apiClient.get('/remediation/plans'),
  getPlan: (planId: string) => apiClient.get(`/remediation/plans/${encodePathSegment(planId)}`),
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
  get: (name: string) => apiClient.get(`/containers/${encodePathSegment(name)}`),
  getLogs: (name: string, lines?: number) => apiClient.get(`/containers/${encodePathSegment(name)}/logs`, { params: { lines: lines ?? 50 } }),
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
  get: (incidentId: string) => apiClient.get(`/incidents/${encodePathSegment(incidentId)}`),
  analyze: (payload: { service_key?: string; asset_id?: string; time_window: string }) => apiClient.post('/incidents/analyze', payload),
  aiSummary: (incidentId: string, payload?: { provider?: string }) =>
    apiClient.post(`/incidents/${encodePathSegment(incidentId)}/ai-summary`, payload ?? {}),
}

export const recommendationsApi = {
  get: (recommendationId: string) => apiClient.get(`/recommendations/${encodePathSegment(recommendationId)}`),
  listFeedback: (recommendationId: string) =>
    apiClient.get(`/recommendations/${encodePathSegment(recommendationId)}/feedback`),
  saveFeedback: (
    recommendationId: string,
    payload: {
      action: RecommendationFeedbackAction
      reason_code?: string
      comment?: string
      operator?: string
      task_id?: string
    },
  ) => apiClient.post(`/recommendations/${encodePathSegment(recommendationId)}/feedback`, payload),
  generate: (payload: { incident_id: string; kinds?: string[] }) => apiClient.post('/recommendations/generate', payload),
  aiReview: (recommendationId: string, payload?: { provider?: string }) =>
    apiClient.post(`/recommendations/${encodePathSegment(recommendationId)}/ai-review`, payload ?? {}),
}

export const tasksApi = {
  list: (params?: { task_type?: string; status?: string }) => apiClient.get('/tasks', { params }),
  get: (taskId: string) => apiClient.get(`/tasks/${encodePathSegment(taskId)}`),
  listArtifacts: (taskId: string, params?: { kind?: string; query?: string; group_by?: 'kind' | 'none' }) =>
    apiClient.get(`/tasks/${encodePathSegment(taskId)}/artifacts`, { params }),
  getDiagnosis: (taskId: string) => apiClient.get(`/tasks/${encodePathSegment(taskId)}/diagnosis`),
  approve: (taskId: string, payload?: { approved_by?: string; approval_note?: string }) =>
    apiClient.post(`/tasks/${encodePathSegment(taskId)}/approve`, payload),
  cancel: (taskId: string) => apiClient.post(`/tasks/${encodePathSegment(taskId)}/cancel`),
  getArtifact: (taskId: string, artifactId: string) => apiClient.get(buildTaskArtifactPath(taskId, artifactId)),
  getArtifactContent: (taskId: string, artifactId: string) =>
    apiClient.get(`${buildTaskArtifactPath(taskId, artifactId)}/content`),
  getArtifactDownloadUrl: (taskId: string, artifactId: string) => `${API_BASE_URL}${buildTaskArtifactPath(taskId, artifactId)}/download`,
}

export const metricsApi = {
  getRecommendation: (params?: {
    start_date?: string
    end_date?: string
    service_key?: string
    provider_name?: string
    model?: string
    version?: string
  }) =>
    apiClient.get('/metrics/recommendation', { params }),
  getAiUsage: (params?: {
    start_date?: string
    end_date?: string
    service_key?: string
    provider_name?: string
    model?: string
    version?: string
    sync_daily?: boolean
  }) =>
    apiClient.get('/metrics/ai-usage', { params }),
}

export const executorsApi = {
  getStatus: (params?: { limit?: number }) => apiClient.get('/executors/status', { params }),
  listReadonlyCommandPacks: (params?: { plugin_key?: string }) =>
    apiClient.get('/executors/readonly-command-packs', { params }),
  run: (payload: {
    plugin_key: string
    command: string
    readonly?: boolean
    timeout_seconds?: number
    task_id?: string
    operator?: string
    approval_ticket?: string
  }) => apiClient.post('/executors/run', payload),
  patchPlugin: (
    pluginKey: string,
    payload: {
      enabled?: boolean
      write_enabled?: boolean
      approval_ticket?: string
    },
  ) => apiClient.patch(`/executors/plugins/${encodePathSegment(pluginKey)}`, payload),
}

export const aiApi = {
  chat: (payload: {
    messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }>
    provider?: string
    temperature?: number
    max_tokens?: number
    task_id?: string
  }) => apiClient.post('/ai/chat', payload),
  testProvider: (payload: { provider_id?: string; provider_name?: string; message?: string }) =>
    apiClient.post('/ai/providers/test', payload),
  listProviders: () => apiClient.get('/ai/providers'),
  listCallLogs: (params?: { provider_name?: string; status?: 'success' | 'error'; limit?: number }) =>
    apiClient.get('/ai/call-logs', { params }),
  createProvider: (payload: {
    name: string
    type: string
    api_key?: string
    model: string
    base_url?: string
    enabled?: boolean
    is_default?: boolean
    timeout?: number
    max_retries?: number
  }) => apiClient.post('/ai/providers', payload),
  updateProvider: (
    providerId: string,
    payload: {
      name?: string
      type?: string
      api_key?: string
      model?: string
      base_url?: string
      enabled?: boolean
      is_default?: boolean
      timeout?: number
      max_retries?: number
    },
  ) => apiClient.patch(`/ai/providers/${encodePathSegment(providerId)}`, payload),
  deleteProvider: (providerId: string) => apiClient.delete(`/ai/providers/${encodePathSegment(providerId)}`),
}

const resolveProviderIdByName = async (providerName: string): Promise<string> => {
  const normalized = providerName.trim()
  if (!normalized) {
    throw new Error('Provider 名称不能为空')
  }

  const payload = await aiApi.listProviders()
  const providers = (payload.providers || []) as LLMProviderRecord[]
  const matched = providers.find((item) => item.name === normalized)
  if (!matched?.provider_id) {
    throw new Error('Provider 不存在')
  }
  return matched.provider_id
}

export const llmApi = {
  listProviders: () => aiApi.listProviders(),
  createProvider: (payload: {
    name: string
    type: string
    api_key?: string
    model: string
    base_url?: string
    enabled?: boolean
    timeout?: number
    max_retries?: number
  }) => aiApi.createProvider(payload),
  updateProvider: async (
    providerName: string,
    payload: {
      type?: string
      api_key?: string
      model?: string
      base_url?: string
      enabled?: boolean
      timeout?: number
      max_retries?: number
    },
  ) => {
    const providerId = await resolveProviderIdByName(providerName)
    return aiApi.updateProvider(providerId, payload)
  },
  deleteProvider: async (providerName: string) => {
    const providerId = await resolveProviderIdByName(providerName)
    return aiApi.deleteProvider(providerId)
  },
  setDefaultProvider: async (providerName: string) => {
    const providerId = await resolveProviderIdByName(providerName)
    return aiApi.updateProvider(providerId, { is_default: true })
  },
  testProvider: async (providerName: string) => {
    const providerId = await resolveProviderIdByName(providerName)
    return aiApi.testProvider({
      provider_id: providerId,
      provider_name: providerName,
      message: '请仅回复 OK',
    })
  },
  listCallLogs: (params?: { provider_name?: string; status?: 'success' | 'error'; limit?: number }) =>
    aiApi.listCallLogs(params),
}

export default apiClient
