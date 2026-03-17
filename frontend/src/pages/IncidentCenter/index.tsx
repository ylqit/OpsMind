import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Drawer, Empty, Input, List, Row, Space, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  aiApi,
  incidentsApi,
  recommendationsApi,
  type AIAssistantStatusResponse,
  type ClaimRecord,
  type IncidentEvidenceRef,
  type IncidentAISummaryResponse,
  type IncidentDetailResponse,
  type IncidentLogSample,
  type IncidentRecommendationTaskLink,
  type IncidentRecord,
  type RecommendationRecord,
  type TaskArtifact,
  type TaskRecord,
} from '@/api/client'
import AIDiagnosisCard from '@/components/ai/AIDiagnosisCard'
import AIProviderStatusStrip from '@/components/ai/AIProviderStatusStrip'
import { CardEmptyState, PageStatusBanner } from '@/components/PageState'
import { useTaskEventStream, type TaskEventMessage } from '@/hooks/useTaskEventStream'
import { useWorkspaceFilterStore } from '@/stores/workspaceFilterStore'

const { Paragraph, Text, Title } = Typography

interface IncidentListResponse {
  items: IncidentRecord[]
  total: number
}

type EvidenceItem = IncidentEvidenceRef

interface RecommendationTaskState {
  taskId: string
  incidentId: string
  taskType: string
  status: string
  currentStage: string
  progress: number
  progressMessage: string
  updatedAt?: string
  errorMessage?: string
  artifactReady: boolean
}

const layerMeta: Record<string, { title: string; color: string; order: number }> = {
  diagnosis: { title: '关联判断', color: 'purple', order: 0 },
  traffic: { title: '流量证据', color: 'blue', order: 1 },
  resource: { title: '资源证据', color: 'orange', order: 2 },
  alert: { title: '告警证据', color: 'red', order: 3 },
  task: { title: '任务证据', color: 'cyan', order: 4 },
  other: { title: '其他证据', color: 'default', order: 5 },
}

const signalStrengthMeta: Record<string, { label: string; color: string }> = {
  high: { label: '高优先', color: 'red' },
  medium: { label: '中优先', color: 'gold' },
  low: { label: '低优先', color: 'default' },
}

const claimMeta: Record<string, { label: string; color: string }> = {
  summary: { label: '结论', color: 'blue' },
  cause: { label: '原因', color: 'purple' },
  action: { label: '动作', color: 'green' },
  risk: { label: '风险', color: 'orange' },
}

const getClaimMeta = (kind: string) => claimMeta[kind] || { label: '判断', color: 'default' }

const incidentEvidenceKindMeta: Record<string, { label: string; color: string }> = {
  artifact: { label: '任务产物', color: 'geekblue' },
  log: { label: '日志片段', color: 'blue' },
  metric: { label: '指标快照', color: 'purple' },
  alert: { label: '告警信号', color: 'red' },
  task: { label: '任务上下文', color: 'cyan' },
  analysis: { label: '关联判断', color: 'gold' },
  other: { label: '其他证据', color: 'default' },
}

const getIncidentEvidenceKindMeta = (kind: string) => incidentEvidenceKindMeta[kind] || incidentEvidenceKindMeta.other

const formatEvidenceValue = (item: EvidenceItem) => {
  if (item.value === undefined || item.value === null || item.value === '') {
    return '-'
  }
  if (typeof item.value === 'number') {
    return `${item.value}${item.unit ? ` ${item.unit}` : ''}`
  }
  return `${String(item.value)}${item.unit ? ` ${item.unit}` : ''}`
}

const pickRecommendationArtifact = (recommendation: RecommendationRecord): TaskArtifact | null => {
  return recommendation.artifact_refs.find((artifact) => artifact.kind === 'diff') || recommendation.artifact_refs.find((artifact) => artifact.kind === 'manifest') || null
}

const formatSampleTime = (value: string) => {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

const sortEvidenceItems = (items: EvidenceItem[]) => {
  return [...items].sort((left, right) => {
    const leftPriority = typeof left.priority === 'number' ? left.priority : 0
    const rightPriority = typeof right.priority === 'number' ? right.priority : 0
    if (leftPriority !== rightPriority) {
      return rightPriority - leftPriority
    }
    return String(left.title || left.metric || '').localeCompare(String(right.title || right.metric || ''))
  })
}

const getIncidentEvidenceLocator = (item: EvidenceItem) => {
  return (item.locator || item.source_ref || {}) as Record<string, unknown>
}

const buildIncidentEvidenceLocatorTags = (item: EvidenceItem) => {
  const locator = getIncidentEvidenceLocator(item)
  const tags: Array<{ key: string; label: string }> = []
  const timestamp = String(locator.timestamp || '').trim()
  const path = String(locator.path || '').trim()
  const clientIp = String(locator.client_ip || '').trim()
  const namespace = String(locator.namespace || '').trim()
  const serviceKey = String(locator.service_key || item.service_key || '').trim()

  if (serviceKey) {
    tags.push({ key: `service-${serviceKey}`, label: `服务 ${serviceKey}` })
  }
  if (path) {
    tags.push({ key: `path-${path}`, label: `路径 ${path}` })
  }
  if (clientIp) {
    tags.push({ key: `ip-${clientIp}`, label: `来源 ${clientIp}` })
  }
  if (namespace) {
    tags.push({ key: `namespace-${namespace}`, label: `命名空间 ${namespace}` })
  }
  if (timestamp) {
    tags.push({ key: `time-${timestamp}`, label: timestamp })
  }
  return tags
}

const getIncidentEvidenceSnippet = (item: EvidenceItem) => {
  const snippet = String(item.snippet || item.quote || '').trim()
  if (snippet) {
    return snippet
  }
  return ''
}

const isProviderUnavailableError = (error: unknown) => {
  if (!(error instanceof Error)) {
    return false
  }
  return error.message.includes('LLM Provider') || error.message.includes('未启用可用的 LLM Provider')
}

const buildRecommendationTaskState = (
  task: Pick<TaskRecord, 'task_id' | 'task_type' | 'status' | 'current_stage' | 'progress' | 'progress_message' | 'updated_at' | 'error'>,
  incidentId: string,
  options?: {
    artifactReady?: boolean
  },
): RecommendationTaskState => ({
  taskId: task.task_id,
  incidentId,
  taskType: task.task_type,
  status: task.status,
  currentStage: task.current_stage,
  progress: task.progress,
  progressMessage: task.progress_message,
  updatedAt: task.updated_at,
  errorMessage: task.error?.error_message,
  artifactReady: options?.artifactReady ?? false,
})

const buildRecommendationTaskStateFromLink = (task: IncidentRecommendationTaskLink, incidentId: string): RecommendationTaskState =>
  buildRecommendationTaskState(task, incidentId, { artifactReady: task.artifact_ready })

const getTaskAlertMeta = (task: RecommendationTaskState) => {
  if (task.status === 'FAILED') {
    return { type: 'error' as const, title: '建议任务执行失败' }
  }
  if (task.status === 'WAITING_CONFIRM') {
    return { type: 'success' as const, title: '建议稿已生成，等待人工确认' }
  }
  if (task.status === 'COMPLETED') {
    return { type: 'success' as const, title: '建议任务已完成' }
  }
  if (task.status === 'CANCELLED') {
    return { type: 'warning' as const, title: '建议任务已取消' }
  }
  return { type: 'info' as const, title: '建议任务正在处理中' }
}

const buildAssistantPrompt = (incident: IncidentRecord) => {
  return `请基于 incident ${incident.incident_id} 的现有证据，总结异常结论、风险和下一步只读排查动作。`
}

export const IncidentCenter: React.FC = () => {
  const navigate = useNavigate()
  const serviceKey = useWorkspaceFilterStore((state) => state.serviceKey)
  const timeRange = useWorkspaceFilterStore((state) => state.timeRange)
  const setServiceKey = useWorkspaceFilterStore((state) => state.setServiceKey)
  const setTimeRange = useWorkspaceFilterStore((state) => state.setTimeRange)
  const [loading, setLoading] = useState(true)
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetailResponse | null>(null)
  const [creating, setCreating] = useState(false)
  const [generatingRecommendation, setGeneratingRecommendation] = useState(false)
  const [aiSummaryLoading, setAiSummaryLoading] = useState(false)
  const [aiSummary, setAiSummary] = useState<IncidentAISummaryResponse | null>(null)
  const [aiProviderReady, setAiProviderReady] = useState<boolean | null>(null)
  const [aiProviderChecking, setAiProviderChecking] = useState(true)
  const [assistantStatus, setAssistantStatus] = useState<AIAssistantStatusResponse | null>(null)
  const [recommendationTask, setRecommendationTask] = useState<RecommendationTaskState | null>(null)
  const [evidenceDrawerOpen, setEvidenceDrawerOpen] = useState(false)
  const [error, setError] = useState('')

  // 先在页面内完成证据分层，保持异常详情、摘要卡片和证据链展示口径一致。
  const groupedEvidence = useMemo(() => {
    const groups: Record<string, EvidenceItem[]> = {}
    const items = (selectedIncident?.incident.evidence_refs || []) as EvidenceItem[]
    for (const item of items) {
      const layer = typeof item.layer === 'string'
        ? item.layer
        : item.type === 'traffic_summary'
          ? 'traffic'
          : item.type === 'resource_summary' || item.type === 'hotspot'
            ? 'resource'
            : item.type === 'alert_signal'
              ? 'alert'
              : item.type === 'task_trace'
                ? 'task'
            : 'other'
      groups[layer] = groups[layer] || []
      groups[layer].push(item)
    }
    return Object.entries(groups)
      .sort((left, right) => (layerMeta[left[0]]?.order || 99) - (layerMeta[right[0]]?.order || 99))
      .map(([layer, items]) => [layer, sortEvidenceItems(items)] as const)
  }, [selectedIncident])

  // 优先展示后端汇总出的诊断摘要，缺失时再回退到证据链和异常本身的摘要字段。
  const diagnosisSummary = useMemo(() => {
    if (!selectedIncident) {
      return null
    }
    const evidenceSummary = selectedIncident.evidence_summary
    const evidenceItems = (selectedIncident.incident.evidence_refs || []) as EvidenceItem[]
    const diagnosisItem = evidenceItems.find((item) => item.layer === 'diagnosis')
    const topEvidence = evidenceSummary?.highlights?.length
      ? evidenceSummary.highlights
      : sortEvidenceItems(evidenceItems.filter((item) => item.layer !== 'diagnosis')).slice(0, 3)
    return {
      conclusion: evidenceSummary?.headline || selectedIncident.incident.summary,
      nextStep: String(evidenceSummary?.next_step || diagnosisItem?.next_step || selectedIncident.incident.recommended_actions[0] || '继续观察关键指标变化'),
      highlights: topEvidence,
      summaryLines: evidenceSummary?.summary_lines || [],
      primaryLayer: evidenceSummary?.primary_layer || 'other',
      layerCounts: evidenceSummary?.layers || {},
    }
  }, [selectedIncident])

  const incidentClaims = useMemo<ClaimRecord[]>(() => selectedIncident?.claims || [], [selectedIncident])
  const aiSummaryClaims = useMemo<ClaimRecord[]>(() => aiSummary?.claims || [], [aiSummary])
  const evidenceHighlights = useMemo(() => diagnosisSummary?.highlights || [], [diagnosisSummary])

  const visibleRecommendationTask = useMemo(() => {
    if (!selectedIncident || !recommendationTask) {
      return null
    }
    if (recommendationTask.incidentId !== selectedIncident.incident.incident_id) {
      return null
    }
    return recommendationTask
  }, [recommendationTask, selectedIncident])

  const latestRecommendation = useMemo(() => {
    if (!selectedIncident?.recommendations.length) {
      return null
    }
    return selectedIncident.recommendations[0]
  }, [selectedIncident])

  const loadIncidents = async () => {
    setLoading(true)
    setError('')
    try {
      const response = (await incidentsApi.list()) as IncidentListResponse
      setIncidents(response.items)
      if (response.items[0]) {
        await loadIncidentDetail(response.items[0].incident_id)
      } else {
        setSelectedIncident(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载异常失败')
    } finally {
      setLoading(false)
    }
  }

  const loadIncidentDetail = useCallback(async (incidentId: string) => {
    try {
      const response = (await incidentsApi.get(incidentId)) as IncidentDetailResponse
      setSelectedIncident(response)
      setRecommendationTask(
        response.recommendation_task
          ? buildRecommendationTaskStateFromLink(response.recommendation_task, response.incident.incident_id)
          : null,
      )
      setAiSummary(null)
      setError('')
      return response
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : '异常详情加载失败')
      throw detailError
    }
  }, [])

  const refreshAIProviderAvailability = useCallback(async () => {
    setAiProviderChecking(true)
    try {
      const payload = (await aiApi.getAssistantStatus()) as AIAssistantStatusResponse
      setAssistantStatus(payload)
      setAiProviderReady(payload.provider_ready)
    } catch {
      // 状态接口失败时不阻塞页面主流程，但会隐藏状态条的细节信息。
      setAssistantStatus(null)
      setAiProviderReady(true)
    } finally {
      setAiProviderChecking(false)
    }
  }, [])

  const createIncidentTask = async () => {
    if (aiProviderReady === false) {
      message.warning('当前未配置可用 AI Provider，请先到 LLM 设置启用后再试')
      return
    }
    setCreating(true)
    try {
      await incidentsApi.analyze({ service_key: serviceKey || undefined, time_window: timeRange })
      await loadIncidents()
    } finally {
      setCreating(false)
    }
  }

  const openRecommendationCenter = (recommendation?: RecommendationRecord) => {
    const incidentId = selectedIncident?.incident.incident_id
    if (!incidentId) {
      return
    }
    // 跳页时把当前 incident 相关上下文带过去，减少建议中心重新定位的成本。
    if (selectedIncident?.incident.service_key) {
      setServiceKey(selectedIncident.incident.service_key)
    }
    const params = new URLSearchParams()
    params.set('incidentId', incidentId)
    if (recommendation) {
      const artifact = pickRecommendationArtifact(recommendation)
      if (artifact) {
        params.set('taskId', artifact.task_id)
        params.set('artifactId', artifact.artifact_id)
      }
    }
    navigate(`/recommendations?${params.toString()}`)
  }

  const openLatestRecommendationDraft = () => {
    if (latestRecommendation) {
      openRecommendationCenter(latestRecommendation)
    }
  }

  const openRecommendationTaskCenter = () => {
    if (!visibleRecommendationTask) {
      return
    }
    navigate(`/tasks?taskId=${encodeURIComponent(visibleRecommendationTask.taskId)}`)
  }

  const openAssistantWorkbench = () => {
    if (!selectedIncident) {
      return
    }
    // AI 助手默认接续当前异常上下文，而不是从空白会话重新开始。
    const params = new URLSearchParams()
    params.set('source', 'incident')
    params.set('incidentId', selectedIncident.incident.incident_id)
    params.set('time_range', timeRange)
    params.set('prompt', buildAssistantPrompt(selectedIncident.incident))
    if (selectedIncident.incident.service_key) {
      setServiceKey(selectedIncident.incident.service_key)
      params.set('service_key', selectedIncident.incident.service_key)
    }
    navigate(`/assistant?${params.toString()}`)
  }

  const openTrafficForIncident = () => {
    if (!selectedIncident) {
      return
    }
    // 通过异常时间窗反推主控台筛选条件，保证跨页联动仍落在同一观察窗口内。
    const params = new URLSearchParams()
    const timeWindowStart = new Date(selectedIncident.incident.time_window_start)
    const timeWindowEnd = new Date(selectedIncident.incident.time_window_end)
    const durationMs = Math.max(0, timeWindowEnd.getTime() - timeWindowStart.getTime())
    const hours = durationMs / (1000 * 60 * 60)
    const timeRange = hours > 6 ? '24h' : hours > 1 ? '6h' : '1h'
    setTimeRange(timeRange)
    setServiceKey(selectedIncident.incident.service_key)
    params.set('time_range', timeRange)
    params.set('service_key', selectedIncident.incident.service_key)
    navigate(`/traffic?${params.toString()}`)
  }

  const openEvidenceDrawer = () => {
    if (!selectedIncident) {
      return
    }
    setEvidenceDrawerOpen(true)
  }

  const jumpToIncidentEvidence = (item: EvidenceItem) => {
    if (!selectedIncident) {
      return
    }
    const locator = getIncidentEvidenceLocator(item)
    const jump = item.jump
    const taskId = String(jump?.task_id || locator.task_id || '').trim()
    const artifactId = String(jump?.artifact_id || locator.artifact_id || item.artifact_id || '').trim()
    const targetServiceKey = String(locator.service_key || selectedIncident.incident.service_key || '').trim()

    // 优先复用任务中心的 artifact 跳转，避免不同页面各自维护一套产物定位逻辑。
    if (taskId && artifactId) {
      setEvidenceDrawerOpen(false)
      navigate(`/tasks?taskId=${encodeURIComponent(taskId)}&artifactId=${encodeURIComponent(artifactId)}`)
      return
    }
    if (taskId) {
      setEvidenceDrawerOpen(false)
      navigate(`/tasks?taskId=${encodeURIComponent(taskId)}`)
      return
    }

    const hasTrafficContext = Boolean(locator.path || locator.client_ip || locator.geo_label || locator.status !== undefined)
    if (hasTrafficContext && targetServiceKey) {
      setServiceKey(targetServiceKey)
      setEvidenceDrawerOpen(false)
      navigate(`/traffic?time_range=${encodeURIComponent(timeRange)}&service_key=${encodeURIComponent(targetServiceKey)}`)
      return
    }

    const assetIds = Array.isArray(locator.asset_ids) ? locator.asset_ids.filter(Boolean) : []
    if ((item.layer === 'resource' || assetIds.length > 0) && targetServiceKey) {
      setServiceKey(targetServiceKey)
      setEvidenceDrawerOpen(false)
      navigate(`/resources?time_range=${encodeURIComponent(timeRange)}&service_key=${encodeURIComponent(targetServiceKey)}`)
      return
    }

    if (targetServiceKey) {
      setServiceKey(targetServiceKey)
      setEvidenceDrawerOpen(false)
      navigate(`/traffic?time_range=${encodeURIComponent(timeRange)}&service_key=${encodeURIComponent(targetServiceKey)}`)
      return
    }

    message.info('当前证据暂不支持直接跳转，请先查看证据摘要')
  }

  const generateRecommendationForIncident = async () => {
    if (!selectedIncident) {
      return
    }
    if (aiProviderReady === false) {
      message.warning('当前未配置可用 AI Provider，请先到 LLM 设置启用后再试')
      return
    }
    setGeneratingRecommendation(true)
    try {
      const task = (await recommendationsApi.generate({ incident_id: selectedIncident.incident.incident_id })) as TaskRecord
      setRecommendationTask(buildRecommendationTaskState(task, selectedIncident.incident.incident_id, { artifactReady: false }))
      message.success('建议生成任务已提交，详情会在当前页面持续更新')
    } finally {
      setGeneratingRecommendation(false)
    }
  }

  const generateAiSummaryForIncident = async () => {
    if (!selectedIncident) {
      return
    }
    if (aiProviderReady === false) {
      message.warning('当前未配置可用 AI Provider，请先到 LLM 设置启用后再试')
      return
    }
    setAiSummaryLoading(true)
    try {
      const response = (await incidentsApi.aiSummary(selectedIncident.incident.incident_id)) as IncidentAISummaryResponse
      setAiSummary(response)
      message.success('已生成 AI 异常摘要')
    } catch (err) {
      if (isProviderUnavailableError(err)) {
        setAiProviderReady(false)
        message.warning('AI Provider 不可用，请先到 LLM 设置完成配置')
        return
      }
      message.error(err instanceof Error ? err.message : 'AI 摘要生成失败')
    } finally {
      setAiSummaryLoading(false)
    }
  }

  // 当前页只消费自己发起的建议任务事件，并在关键节点回刷异常详情拿到最新草稿。
  const handleTaskEvent = useCallback((event: TaskEventMessage) => {
    if (!recommendationTask || event.task_id !== recommendationTask.taskId) {
      return
    }

    setRecommendationTask((previous) => {
      if (!previous || event.task_id !== previous.taskId) {
        return previous
      }
      const next: RecommendationTaskState = {
        ...previous,
        status: typeof event.status === 'string' ? event.status : previous.status,
        currentStage: typeof event.current_stage === 'string' ? event.current_stage : previous.currentStage,
        progress: typeof event.progress === 'number' ? event.progress : previous.progress,
        progressMessage: typeof event.progress_message === 'string' ? event.progress_message : previous.progressMessage,
        updatedAt: typeof event.updated_at === 'string' ? event.updated_at : previous.updatedAt,
        artifactReady: previous.artifactReady || event.type === 'task_artifact_ready',
      }
      const eventError = event.error as { error_message?: string } | undefined
      if (event.type === 'task_failed') {
        next.errorMessage = typeof eventError?.error_message === 'string' ? eventError.error_message : next.progressMessage
      }
      return next
    })

    if (['task_artifact_ready', 'task_waiting_confirm', 'task_completed', 'task_failed'].includes(event.type)) {
      void loadIncidentDetail(recommendationTask.incidentId)
    }
  }, [loadIncidentDetail, recommendationTask])

  const { connected: taskEventConnected } = useTaskEventStream({
    enabled: true,
    onEvent: handleTaskEvent,
  })

  useEffect(() => {
    void loadIncidents()
    void refreshAIProviderAvailability()
  }, [refreshAIProviderAvailability])

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>异常中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            按服务维度收拢症状、证据链和建议入口，用同一个视图完成排查与判断。
          </Paragraph>
        </div>
        <Space wrap>
          <Input value={serviceKey} onChange={(event) => setServiceKey(event.target.value)} placeholder="service_key，例如 docker/nginx" style={{ width: 220 }} />
          <Button onClick={openAssistantWorkbench} disabled={!selectedIncident}>
            AI 助手
          </Button>
          <Button
            type="primary"
            loading={creating}
            disabled={aiProviderReady === false || aiProviderChecking}
            onClick={() => void createIncidentTask()}
          >
            发起分析
          </Button>
        </Space>
      </div>

      {error ? (
        <PageStatusBanner
          type="error"
          title="异常中心加载失败"
          description={error}
          actionText="重新加载"
          onAction={() => void loadIncidents()}
        />
      ) : null}
      <AIProviderStatusStrip
        status={assistantStatus}
        loading={aiProviderChecking}
        onOpenSettings={() => navigate('/llm-settings')}
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card title="异常列表" loading={loading} className="ops-surface-card">
            <List
              dataSource={incidents}
              locale={{ emptyText: '暂无异常记录' }}
              renderItem={(incident) => (
                <List.Item onClick={() => void loadIncidentDetail(incident.incident_id)} style={{ cursor: 'pointer' }}>
                  <div style={{ width: '100%' }}>
                    <Space style={{ marginBottom: 8 }}>
                      <Tag color={incident.severity === 'critical' ? 'red' : incident.severity === 'warning' ? 'orange' : 'blue'}>{incident.severity}</Tag>
                      <Text strong>{incident.title}</Text>
                    </Space>
                    <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 4 }}>{incident.summary}</Paragraph>
                    <Text type="secondary">{incident.service_key}</Text>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card
            title="异常详情"
            loading={loading}
            className="ops-surface-card"
            extra={
              <Space>
                <Button
                  type="primary"
                  ghost
                  onClick={() => void generateRecommendationForIncident()}
                  disabled={!selectedIncident || aiProviderReady === false || aiProviderChecking}
                  loading={generatingRecommendation || aiProviderChecking}
                >
                  生成建议
                </Button>
                <Button
                  onClick={() => void generateAiSummaryForIncident()}
                  disabled={!selectedIncident || aiProviderReady === false || aiProviderChecking}
                  loading={aiSummaryLoading || aiProviderChecking}
                >
                  AI 总结
                </Button>
                <Button onClick={openEvidenceDrawer} disabled={!selectedIncident}>
                  查看证据
                </Button>
                <Button onClick={() => openRecommendationCenter()} disabled={!selectedIncident}>
                  打开建议中心
                </Button>
              </Space>
            }
          >
            {!selectedIncident ? (
              <CardEmptyState title="请选择一个异常" description="也可以先发起分析任务生成新的异常记录" />
            ) : (
              <div>
                <Space style={{ marginBottom: 12, flexWrap: 'wrap' }}>
                  <Tag color={selectedIncident.incident.severity === 'critical' ? 'red' : 'orange'}>{selectedIncident.incident.severity}</Tag>
                  <Text strong>{selectedIncident.incident.title}</Text>
                  <Tag color="geekblue">置信度 {Math.round(selectedIncident.incident.confidence * 100)}%</Tag>
                </Space>
                <Paragraph>{selectedIncident.incident.summary}</Paragraph>
                <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>服务键：{selectedIncident.incident.service_key}</Paragraph>
                  <Button type="link" size="small" onClick={openTrafficForIncident}>查看对应流量</Button>
                </Space>
                <Space wrap style={{ marginBottom: 16 }}>
                  {selectedIncident.incident.reasoning_tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </Space>

                {visibleRecommendationTask ? (
                  <Alert
                    showIcon
                    type={getTaskAlertMeta(visibleRecommendationTask).type}
                    message={getTaskAlertMeta(visibleRecommendationTask).title}
                    description={
                      <div>
                        <Paragraph style={{ marginBottom: 8 }}>
                          当前阶段：{visibleRecommendationTask.currentStage} · 进度 {visibleRecommendationTask.progress}% · {visibleRecommendationTask.progressMessage || '等待任务更新'}
                        </Paragraph>
                        <Space wrap>
                          <Tag color={taskEventConnected ? 'green' : 'default'}>{taskEventConnected ? '事件流已连接' : '事件流重连中'}</Tag>
                          <Tag color={visibleRecommendationTask.artifactReady ? 'cyan' : 'default'}>{visibleRecommendationTask.artifactReady ? '草稿已产出' : '草稿生成中'}</Tag>
                          <Tag color={visibleRecommendationTask.status === 'FAILED' ? 'red' : visibleRecommendationTask.status === 'WAITING_CONFIRM' ? 'gold' : 'blue'}>{visibleRecommendationTask.status}</Tag>
                        </Space>
                        {visibleRecommendationTask.errorMessage ? (
                          <Paragraph type="danger" style={{ marginTop: 8, marginBottom: 0 }}>
                            失败原因：{visibleRecommendationTask.errorMessage}
                          </Paragraph>
                        ) : null}
                      </div>
                    }
                    action={
                      <Space direction="vertical" size={8}>
                        <Button size="small" onClick={openRecommendationTaskCenter}>
                          打开任务中心
                        </Button>
                        <Button size="small" onClick={openLatestRecommendationDraft} disabled={!latestRecommendation}>
                          打开最新草稿
                        </Button>
                      </Space>
                    }
                    style={{ marginBottom: 16 }}
                  />
                ) : null}

                {diagnosisSummary ? (
                  <Card type="inner" title="诊断摘要" style={{ marginBottom: 16 }}>
                    <div className="ops-incident-brief">
                      <Paragraph className="ops-incident-brief__headline">{diagnosisSummary.conclusion}</Paragraph>
                      <div className="ops-incident-brief__next-step">
                        <Text strong>建议先做：</Text>
                        <Text>{diagnosisSummary.nextStep}</Text>
                      </div>
                      <Space wrap style={{ marginBottom: 12 }}>
                        <Tag color={layerMeta[diagnosisSummary.primaryLayer]?.color || layerMeta.other.color}>
                          主要证据层：{layerMeta[diagnosisSummary.primaryLayer]?.title || layerMeta.other.title}
                        </Tag>
                        {Object.entries(diagnosisSummary.layerCounts).map(([layer, count]) => (
                          <Tag key={layer}>
                            {layerMeta[layer]?.title || layerMeta.other.title} {count}
                          </Tag>
                        ))}
                      </Space>
                      {diagnosisSummary.summaryLines.length ? (
                        <List
                          size="small"
                          dataSource={diagnosisSummary.summaryLines}
                          split={false}
                          style={{ marginBottom: 12 }}
                          renderItem={(item) => <List.Item style={{ paddingBlock: 4 }}>{item}</List.Item>}
                        />
                      ) : null}
                      {incidentClaims.length ? (
                        <List
                          size="small"
                          header={<Text strong>结论拆解</Text>}
                          dataSource={incidentClaims}
                          style={{ marginBottom: 12 }}
                          renderItem={(item) => {
                            const meta = getClaimMeta(item.kind)
                            return (
                              <List.Item>
                                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                                  <Space wrap>
                                    <Tag color={meta.color}>{meta.label}</Tag>
                                    {item.title ? <Text strong>{item.title}</Text> : null}
                                    <Tag color="blue">置信度 {Math.round((item.confidence || 0) * 100)}%</Tag>
                                    <Tag>证据 {item.evidence_ids.length}</Tag>
                                  </Space>
                                  <Paragraph style={{ marginBottom: 0 }}>{item.statement}</Paragraph>
                                  {item.limitations.length ? (
                                    <Text type="secondary">限制：{item.limitations.join('；')}</Text>
                                  ) : null}
                                </Space>
                              </List.Item>
                            )
                          }}
                        />
                      ) : null}
                      <div className="ops-incident-brief__highlights">
                        {diagnosisSummary.highlights.length > 0 ? diagnosisSummary.highlights.map((item) => (
                          <div key={`${item.layer}-${item.metric}-${item.title}`} className="ops-incident-brief__highlight">
                            <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                              <Tag color={layerMeta[item.layer || 'other']?.color || layerMeta.other.color}>{layerMeta[item.layer || 'other']?.title || layerMeta.other.title}</Tag>
                              <Text strong>{String(item.title || item.metric || '关键证据')}</Text>
                              <Tag>{formatEvidenceValue(item)}</Tag>
                              <Button size="small" type="link" onClick={() => openEvidenceDrawer()}>
                                查看详情
                              </Button>
                            </Space>
                            <Paragraph style={{ marginBottom: 0 }}>{String(item.summary || '-')}</Paragraph>
                          </div>
                        )) : <CardEmptyState title="暂无高优先证据" />}
                      </div>
                    </div>
                  </Card>
                ) : null}

                {aiSummary ? (
                  <Card type="inner" title="AI 异常总结" style={{ marginBottom: 16 }}>
                    <AIDiagnosisCard
                      summary={aiSummary.summary}
                      riskLevel={aiSummary.risk_level}
                      confidence={aiSummary.confidence}
                      provider={aiSummary.provider}
                      parseMode={aiSummary.parse_mode}
                      primaryCauses={aiSummary.primary_causes}
                      recommendedActions={aiSummary.recommended_actions}
                      evidenceCitations={aiSummary.evidence_citations}
                      roleViews={aiSummary.role_views}
                    />
                    {aiSummaryClaims.length ? (
                      <List
                        size="small"
                        header={<Text strong>AI 结论拆解</Text>}
                        dataSource={aiSummaryClaims}
                        style={{ marginTop: 12 }}
                        renderItem={(item) => {
                          const meta = getClaimMeta(item.kind)
                          return (
                            <List.Item>
                              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                                <Space wrap>
                                  <Tag color={meta.color}>{meta.label}</Tag>
                                  {item.title ? <Text strong>{item.title}</Text> : null}
                                  <Tag color="blue">置信度 {Math.round((item.confidence || 0) * 100)}%</Tag>
                                  <Tag>证据 {item.evidence_ids.length}</Tag>
                                </Space>
                                <Paragraph style={{ marginBottom: 0 }}>{item.statement}</Paragraph>
                                {item.limitations.length ? (
                                  <Text type="secondary">限制：{item.limitations.join('；')}</Text>
                                ) : null}
                              </Space>
                            </List.Item>
                          )
                        }}
                      />
                    ) : null}
                  </Card>
                ) : null}

                <Card type="inner" title="证据链分层" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    {groupedEvidence.map(([layer, items]) => (
                      <Card key={layer} size="small" title={layerMeta[layer]?.title || layerMeta.other.title} extra={<Tag color={layerMeta[layer]?.color || layerMeta.other.color}>{items.length} 条</Tag>}>
                        <List
                          size="small"
                          dataSource={items}
                          renderItem={(item) => {
                            const signalMeta = signalStrengthMeta[item.signal_strength || 'low'] || signalStrengthMeta.low
                            const evidenceMeta = getIncidentEvidenceKindMeta(item.kind)
                            return (
                              <List.Item
                                actions={[
                                  <Button key={`view-${item.evidence_id}`} size="small" type="link" onClick={() => openEvidenceDrawer()}>
                                    查看证据
                                  </Button>,
                                  <Button key={`jump-${item.evidence_id}`} size="small" onClick={() => jumpToIncidentEvidence(item)}>
                                    跳转定位
                                  </Button>,
                                ]}
                              >
                                <div style={{ width: '100%' }}>
                                  <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                                    <Text strong>{String(item.title || item.name || item.metric || item.type || '证据项')}</Text>
                                    <Tag color={evidenceMeta.color}>{evidenceMeta.label}</Tag>
                                    <Tag>{String(item.metric || item.type || 'metric')}</Tag>
                                    <Tag color="default">{formatEvidenceValue(item)}</Tag>
                                    <Tag color={signalMeta.color}>{signalMeta.label}</Tag>
                                    <Tag color="geekblue">优先级 {item.priority || 0}</Tag>
                                  </Space>
                                  <Paragraph style={{ marginBottom: 0 }}>{String(item.summary || item.reason || '-')}</Paragraph>
                                  {item.next_step ? (
                                    <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
                                      下一步：{String(item.next_step)}
                                    </Paragraph>
                                  ) : null}
                                </div>
                              </List.Item>
                            )
                          }}
                        />
                      </Card>
                    ))}
                  </Space>
                </Card>

                <Card type="inner" title="日志证据样本" style={{ marginBottom: 16 }}>
                  <List
                    dataSource={selectedIncident.log_samples || []}
                    locale={{ emptyText: '当前时间窗内没有可展示的访问样本' }}
                    renderItem={(item: IncidentLogSample) => (
                      <List.Item>
                        <div style={{ width: '100%' }}>
                          <Space style={{ marginBottom: 8, flexWrap: 'wrap' }}>
                            <Tag color={item.status >= 500 ? 'red' : item.status >= 400 ? 'orange' : 'blue'}>{item.status}</Tag>
                            <Tag>{item.method}</Tag>
                            <Text code>{item.path}</Text>
                            <Tag color="geekblue">{item.latency_ms} ms</Tag>
                          </Space>
                          <Paragraph style={{ marginBottom: 8 }}>
                            {formatSampleTime(item.timestamp)} · {item.client_ip} · {item.geo_label}
                          </Paragraph>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            {item.browser} / {item.os} / {item.device} · {item.user_agent}
                          </Paragraph>
                        </div>
                      </List.Item>
                    )}
                  />
                </Card>

                <Card type="inner" title="推荐动作" style={{ marginBottom: 16 }}>
                  <List
                    dataSource={selectedIncident.incident.recommended_actions}
                    locale={{ emptyText: '暂无建议动作' }}
                    renderItem={(item) => <List.Item>{item}</List.Item>}
                  />
                </Card>
                <Card type="inner" title="已生成建议">
                  <List
                    dataSource={selectedIncident.recommendations}
                    locale={{ emptyText: '当前还没有建议内容' }}
                    renderItem={(item) => (
                      <List.Item
                        actions={[
                          <Button key="open" size="small" type="primary" ghost onClick={() => openRecommendationCenter(item)}>
                            打开草稿
                          </Button>,
                        ]}
                      >
                        <div style={{ width: '100%' }}>
                          <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                            <Tag>{item.kind}</Tag>
                            <Text>{item.recommendation}</Text>
                          </Space>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>{item.risk_note}</Paragraph>
                        </div>
                      </List.Item>
                    )}
                  />
                </Card>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Drawer
        title="证据抽屉"
        open={evidenceDrawerOpen}
        width={600}
        onClose={() => setEvidenceDrawerOpen(false)}
        destroyOnClose={false}
      >
        {!selectedIncident ? (
          <Empty description="请选择一个异常后查看证据详情" />
        ) : (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message="证据链与跳转定位"
              description={`当前异常共有 ${selectedIncident.evidence_summary.total} 条证据，可按层查看，并跳到任务产物、流量页或资源页继续排查。`}
            />
            <Space wrap>
              <Tag color="blue">异常 {selectedIncident.incident.incident_id}</Tag>
              <Tag color="purple">服务 {selectedIncident.incident.service_key}</Tag>
              <Tag color="geekblue">高亮证据 {evidenceHighlights.length}</Tag>
              {Object.entries(selectedIncident.evidence_summary.layers || {}).map(([layer, count]) => (
                <Tag key={`drawer-layer-${layer}`} color={layerMeta[layer]?.color || layerMeta.other.color}>
                  {layerMeta[layer]?.title || layerMeta.other.title} {count}
                </Tag>
              ))}
            </Space>

            <Card type="inner" title="现场日志样本" size="small">
              <List
                size="small"
                dataSource={(selectedIncident.log_samples || []).slice(0, 5)}
                locale={{ emptyText: '当前时间窗内没有可展示的访问样本' }}
                renderItem={(item: IncidentLogSample) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space style={{ marginBottom: 8, flexWrap: 'wrap' }}>
                        <Tag color={item.status >= 500 ? 'red' : item.status >= 400 ? 'orange' : 'blue'}>{item.status}</Tag>
                        <Tag>{item.method}</Tag>
                        <Text code>{item.path}</Text>
                        <Tag color="geekblue">{item.latency_ms} ms</Tag>
                      </Space>
                      <Paragraph style={{ marginBottom: 4 }}>
                        {formatSampleTime(item.timestamp)} · {item.client_ip} · {item.geo_label}
                      </Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {item.browser} / {item.os} / {item.device}
                      </Paragraph>
                    </div>
                  </List.Item>
                )}
              />
            </Card>

            {groupedEvidence.map(([layer, items]) => (
              <Card
                key={`drawer-group-${layer}`}
                type="inner"
                title={layerMeta[layer]?.title || layerMeta.other.title}
                size="small"
                extra={<Tag color={layerMeta[layer]?.color || layerMeta.other.color}>{items.length} 条</Tag>}
              >
                <List
                  size="small"
                  dataSource={items}
                  renderItem={(item) => {
                    const signalMeta = signalStrengthMeta[item.signal_strength || 'low'] || signalStrengthMeta.low
                    const evidenceMeta = getIncidentEvidenceKindMeta(item.kind)
                    const snippet = getIncidentEvidenceSnippet(item)
                    const locatorTags = buildIncidentEvidenceLocatorTags(item)
                    return (
                      <List.Item
                        actions={[
                          <Button key={`jump-drawer-${item.evidence_id}`} size="small" onClick={() => jumpToIncidentEvidence(item)}>
                            跳转定位
                          </Button>,
                        ]}
                      >
                        <div style={{ width: '100%' }}>
                          <Space wrap style={{ marginBottom: 6 }}>
                            <Tag color={evidenceMeta.color}>{evidenceMeta.label}</Tag>
                            <Text strong>{String(item.title || item.metric || item.type || '证据项')}</Text>
                            <Tag>{String(item.metric || item.type || 'metric')}</Tag>
                            <Tag color="default">{formatEvidenceValue(item)}</Tag>
                            <Tag color={signalMeta.color}>{signalMeta.label}</Tag>
                            <Tag color="geekblue">优先级 {item.priority || 0}</Tag>
                            {item.confidence ? <Tag color="blue">置信度 {Math.round(item.confidence * 100)}%</Tag> : null}
                          </Space>
                          <Paragraph style={{ marginBottom: 6 }}>{String(item.summary || '-')}</Paragraph>
                          {snippet ? (
                            <Paragraph type="secondary" style={{ marginBottom: 6, whiteSpace: 'pre-wrap' }}>
                              {snippet}
                            </Paragraph>
                          ) : null}
                          {locatorTags.length ? (
                            <Space wrap>
                              {locatorTags.map((tag) => (
                                <Tag key={tag.key}>{tag.label}</Tag>
                              ))}
                            </Space>
                          ) : null}
                          {item.next_step ? (
                            <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
                              下一步：{String(item.next_step)}
                            </Paragraph>
                          ) : null}
                        </div>
                      </List.Item>
                    )
                  }}
                />
              </Card>
            ))}
          </Space>
        )}
      </Drawer>
    </div>
  )
}

export default IncidentCenter
