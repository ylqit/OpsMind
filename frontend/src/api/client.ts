import axios from 'axios'
import { getErrorMessage, getErrorType } from '@/utils/errorHandler'

// 前端统一通过这一层消费后端契约，页面与 store 不直接拼接原始请求细节。
const API_BASE_URL = '/api'

const encodePathSegment = (value: string) => encodeURIComponent(value)

// 产物相关 URL 统一在这里编码，避免任务页和建议页各自拼接路径。
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

// 共享领域类型：总览、异常、建议、任务和执行插件页面都依赖这些结构。
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

export interface EvidenceTimeRange {
  start?: string | null
  end?: string | null
}

export interface EvidenceLocator {
  service_key?: string
  asset_ids?: string[]
  task_id?: string
  trace_id?: string
  alert_id?: string
  artifact_id?: string
  execution_id?: string
  timestamp?: string
  path?: string
  status?: string | number
  source?: string
  namespace?: string
  client_ip?: string
  geo_label?: string
  layer?: string
  jump_kind?: string
  [key: string]: unknown
}

export interface EvidenceRef {
  evidence_id: string
  kind: string
  source: string
  title: string
  summary: string
  time_range?: EvidenceTimeRange | null
  locator?: EvidenceLocator
  artifact_id?: string | null
  snippet?: string
  confidence?: number
  layer: string
  type: string
  source_type: string
  metric: string
  value?: unknown
  unit?: string
  priority: number
  signal_strength: 'high' | 'medium' | 'low'
  source_ref: EvidenceLocator
  tags: string[]
  service_key?: string
  next_step?: string
  reasoning_tags?: string[]
  alignment?: Record<string, unknown>
  quote?: string
  artifact_ref?: TaskArtifact | null
  jump?: {
    kind: 'artifact' | 'none'
    task_id?: string
    artifact_id?: string
  }
  [key: string]: unknown
}

export interface ClaimRecord {
  claim_id: string
  kind: string
  statement: string
  evidence_ids: string[]
  confidence: number
  limitations: string[]
  title?: string
  source?: string
  next_step?: string | null
  [key: string]: unknown
}

export interface DiagnosisReport {
  summary: string
  claims: ClaimRecord[]
  evidence_refs: EvidenceRef[]
  limitations: string[]
  next_actions: string[]
  risk_level: 'high' | 'medium' | 'low' | string
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

export type IncidentEvidenceRef = EvidenceRef

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

export interface IncidentBaselineHighlight {
  highlight_id: string
  layer: string
  metric: string
  title: string
  summary: string
  current_value?: number | string | null
  baseline_value?: number | string | null
  delta_value?: number | string | null
  delta_percent?: number | null
  unit?: string
  severity: 'high' | 'medium' | 'low' | string
  direction: 'up' | 'down' | 'flat' | string
  source: string
  next_step?: string
}

export interface IncidentBaselineSummary {
  status: 'ready' | 'partial' | 'unavailable' | string
  headline: string
  message: string
  next_step?: string
  source_modes: string[]
  layers: Record<string, number>
  highlights: IncidentBaselineHighlight[]
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

export type RecommendationEvidenceRef = EvidenceRef

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
  claims: ClaimRecord[]
  diagnosis_report: DiagnosisReport
  assistant_writebacks?: AIWritebackRecord[]
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

export interface TaskDiagnosisTimelineItem {
  item_id: string
  category: 'task' | 'incident' | 'recommendation' | 'trace' | 'executor' | 'artifact' | 'writeback' | 'approval' | 'failure' | string
  title: string
  summary: string
  occurred_at: string
  status: string
  tags: string[]
  links: {
    task_id?: string
    incident_id?: string
    recommendation_id?: string
    artifact_id?: string
    execution_id?: string
  }
  meta: Record<string, unknown>
}

export interface TaskDiagnosisTimelineSummary {
  total: number
  categories: Record<string, number>
  first_event_at: string
  last_event_at: string
}

export interface TaskDetailResponse {
  task: TaskRecord
  trace_preview: Array<Record<string, unknown>>
  artifacts: TaskArtifact[]
  failure_diagnosis?: TaskFailureDiagnosis | null
  assistant_writebacks?: AIWritebackRecord[]
  diagnosis_timeline: TaskDiagnosisTimelineItem[]
  diagnosis_timeline_summary: TaskDiagnosisTimelineSummary
}

export type IncidentLogSample = LogSampleRecord

export interface IncidentDetailResponse {
  incident: IncidentRecord
  recommendations: RecommendationRecord[]
  log_samples: LogSampleRecord[]
  evidence_summary: IncidentEvidenceSummary
  baseline_summary: IncidentBaselineSummary
  claims: ClaimRecord[]
  diagnosis_report: DiagnosisReport
  assistant_writebacks?: AIWritebackRecord[]
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
  claims: ClaimRecord[]
  role_views?: AISummaryRoleViews
  parse_mode: string
  validation_status?: string
  retry_count?: number
  guardrail_error_code?: string
  guardrail_error_message?: string
  log_sample_count: number
  recommendation_count: number
  diagnosis_report: DiagnosisReport
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
  claims: ClaimRecord[]
  role_views?: AISummaryRoleViews
  parse_mode: string
  validation_status?: string
  retry_count?: number
  guardrail_error_code?: string
  guardrail_error_message?: string
  diagnosis_report: DiagnosisReport
}

export interface AIAssistantCommandSuggestion {
  plugin_key: string
  plugin_name: string
  category_key: string
  category_label: string
  template_id: string
  title: string
  description: string
  command: string
}

export type AnalysisSessionSource = 'manual' | 'incident' | 'recommendation'

export interface AnalysisSessionRecord {
  session_id: string
  source: AnalysisSessionSource
  title: string
  prompt: string
  service_key: string
  time_range: string
  incident_id?: string | null
  recommendation_id?: string | null
  evidence_ids: string[]
  executor_result_ids: string[]
  created_at: string
  updated_at: string
}

export type AIWritebackKind = 'incident_summary_draft' | 'recommendation_rationale' | 'executor_followup'

export interface AIWritebackRecord {
  writeback_id: string
  session_id?: string | null
  kind: AIWritebackKind
  title: string
  summary: string
  content: string
  provider: string
  status: string
  source: string
  incident_id?: string | null
  recommendation_id?: string | null
  task_id?: string | null
  claims: ClaimRecord[]
  command_suggestions: AIAssistantCommandSuggestion[]
  created_at: string
  updated_at: string
}

export type AIAssistantProviderStatus = 'ready' | 'degraded' | 'unavailable'

export interface AIAssistantStatusResponse {
  status: AIAssistantProviderStatus
  status_message: string
  provider_ready: boolean
  degraded_reason: string
  default_provider: string
  default_provider_id: string
  default_model: string
  provider_source: 'router' | 'repository' | 'none'
  router_default_provider: string
  providers_total: number
  enabled_providers: number
  configured_providers: number
  command_suggestions: AIAssistantCommandSuggestion[]
}

export interface AIAssistantDiagnoseResponse {
  status: 'success' | 'degraded'
  answer: string
  provider: string
  degraded_reason: string
  latency_ms: number
  command_suggestions: AIAssistantCommandSuggestion[]
  diagnosis_report: DiagnosisReport
  context: {
    session_id: string
    service_key: string
    time_range: string
    incident_id: string
    recommendation_id: string
    evidence_ids: string[]
    executor_result_ids: string[]
  }
}

export interface AIAssistantWritebackSaveResponse {
  message: string
  writeback: AIWritebackRecord
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

export interface ExecutorRecommendedCommandPack extends ExecutorReadonlyCommandPack {
  score: number
  reason: string
  already_executed: boolean
}

export interface ExecutorRecommendedCommandGroup {
  plugin_key: string
  display_name: string
  priority: number
  reason: string
  recommended_command_packs: ExecutorRecommendedCommandPack[]
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

export interface ExecutorFailureDigest extends ExecutorAuditLog {
  stderr_summary?: string
  approval_required?: boolean
  has_approval_ticket?: boolean
}

export interface ExecutorExecutionContext {
  mode: 'local' | 'remote' | string
  remote_kind?: string
  remote_target?: string
  remote_namespace?: string
  remote_enabled?: boolean
}

export interface ExecutorStatusResponse {
  plugins: ExecutorPluginStatus[]
  recent_logs: ExecutorAuditLog[]
  recent_failures?: ExecutorFailureDigest[]
  recent_limit?: number
  summary: {
    total: number
    enabled: number
    degraded: number
    success?: number
    error?: number
    timeout?: number
    rejected?: number
    circuit_open?: number
    approval_required?: number
    circuit_open_plugins?: number
    top_error_codes?: Array<{
      error_code: string
      count: number
    }>
  }
}

export interface ExecutorRunResponse {
  execution: ExecutorAuditLog
  plugin: ExecutorPluginStatus
  execution_context?: ExecutorExecutionContext
  evidence?: {
    source: string
    generated_at: string
    summary: string
    evidence_refs: EvidenceRef[]
  }
  task_evidence?: {
    linked: boolean
    reason?: string
    message?: string
    task_id?: string
    artifact_id?: string
    execution_id?: string
  }
  analysis_session?: {
    linked: boolean
    reason?: string
    session_id?: string
    execution_id?: string
    executor_result_ids?: string[]
    service_key?: string
    time_range?: string
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

export interface ExecutorRecommendedCommandPackResponse {
  context: {
    session_id: string
    incident_id: string
    recommendation_id: string
    service_key: string
    time_range: string
    recommendation_kind: string
    reasoning_tags: string[]
    evidence_layers: string[]
    signals: string[]
    executor_result_ids: string[]
  }
  items: ExecutorRecommendedCommandGroup[]
  recommended_total: number
  total: number
}

type HttpClient = {
  get<T = any>(url: string, config?: unknown): Promise<T>
  post<T = any>(url: string, data?: unknown, config?: unknown): Promise<T>
  put<T = any>(url: string, data?: unknown, config?: unknown): Promise<T>
  patch<T = any>(url: string, data?: unknown, config?: unknown): Promise<T>
  delete<T = any>(url: string, config?: unknown): Promise<T>
}

// 统一 HTTP 客户端：请求超时和错误文案都在这里收口。
const rawApiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 在客户端统一规范错误文案，减少页面重复判断 HTTP 状态码。
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

// 能力调试与兼容入口。
export const capabilitiesApi = {
  list: () => apiClient.get('/capabilities'),
  getSchema: (name: string) => apiClient.get(`/capabilities/${encodePathSegment(name)}/schema`),
  dispatch: (name: string, params: Record<string, unknown>) => apiClient.post(`/capabilities/${encodePathSegment(name)}/dispatch`, { params }),
}

// 仪表盘与分析聚合接口。
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

// 异常、建议与任务主链路接口。
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

// 质量与评估指标接口。
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

// 执行插件与只读诊断接口。
export const executorsApi = {
  getStatus: (params?: { limit?: number }) => apiClient.get('/executors/status', { params }),
  getExecution: (executionId: string) => apiClient.get(`/executors/executions/${encodePathSegment(executionId)}`),
  listReadonlyCommandPacks: (params?: { plugin_key?: string }) =>
    apiClient.get('/executors/readonly-command-packs', { params }),
  getRecommendedCommandPacks: (params?: {
    session_id?: string
    incident_id?: string
    recommendation_id?: string
    plugin_key?: string
    limit?: number
  }) => apiClient.get('/executors/recommended-command-packs', { params }),
  run: (payload: {
    plugin_key: string
    command: string
    readonly?: boolean
    timeout_seconds?: number
    task_id?: string
    session_id?: string
    operator?: string
    approval_ticket?: string
    execution_context?: ExecutorExecutionContext
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

// AI Provider、助手和调用日志接口。
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
  getAssistantStatus: () => apiClient.get('/ai/assistant/status'),
  createAssistantSession: (payload: {
    session_id?: string
    source?: AnalysisSessionSource
    title?: string
    prompt?: string
    service_key?: string
    time_range?: string
    incident_id?: string
    recommendation_id?: string
    evidence_ids?: string[]
    executor_result_ids?: string[]
  }) => apiClient.post('/ai/assistant/sessions', payload),
  getAssistantSession: (sessionId: string) => apiClient.get(`/ai/assistant/sessions/${encodePathSegment(sessionId)}`),
  updateAssistantSession: (
    sessionId: string,
    payload: {
      source?: AnalysisSessionSource
      title?: string
      prompt?: string
      service_key?: string
      time_range?: string
      incident_id?: string
      recommendation_id?: string
      evidence_ids?: string[]
      executor_result_ids?: string[]
    },
  ) => apiClient.patch(`/ai/assistant/sessions/${encodePathSegment(sessionId)}`, payload),
  diagnoseWithAssistant: (payload: {
    message: string
    session_id?: string
    service_key?: string
    time_range?: string
    incident_id?: string
    recommendation_id?: string
    evidence_ids?: string[]
    executor_result_ids?: string[]
    provider?: string
    temperature?: number
    max_tokens?: number
    task_id?: string
    include_command_packs?: boolean
  }) => apiClient.post('/ai/assistant/diagnose', payload),
  saveAssistantWriteback: (payload: {
    session_id?: string
    kind: AIWritebackKind
    title?: string
    summary?: string
    content: string
    provider?: string
    status?: string
    incident_id?: string
    recommendation_id?: string
    task_id?: string
    claims?: ClaimRecord[]
    command_suggestions?: AIAssistantCommandSuggestion[]
  }) => apiClient.post('/ai/assistant/writebacks', payload),
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

// 兼容层：旧页面仍可通过 llmApi 调用，内部统一转发到 aiApi。
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
