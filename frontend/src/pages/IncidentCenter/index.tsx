import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, List, Row, Space, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  aiApi,
  incidentsApi,
  recommendationsApi,
  type IncidentAISummaryResponse,
  type IncidentDetailResponse,
  type IncidentLogSample,
  type IncidentRecord,
  type LLMProviderRecord,
  type RecommendationRecord,
  type TaskArtifact,
  type TaskRecord,
} from '@/api/client'
import { useTaskEventStream, type TaskEventMessage } from '@/hooks/useTaskEventStream'

const { Paragraph, Text, Title } = Typography

interface IncidentListResponse {
  items: IncidentRecord[]
  total: number
}

interface EvidenceItem {
  layer?: string
  type?: string
  title?: string
  summary?: string
  metric?: string
  value?: unknown
  unit?: string
  reason?: string
  name?: string
  priority?: number
  signal_strength?: string
  next_step?: string
  reasoning_tags?: string[]
  [key: string]: unknown
}

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
  other: { title: '其他证据', color: 'default', order: 3 },
}

const signalStrengthMeta: Record<string, { label: string; color: string }> = {
  high: { label: '高优先', color: 'red' },
  medium: { label: '中优先', color: 'gold' },
  low: { label: '低优先', color: 'default' },
}

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

const hasUsableAIProvider = (providers: LLMProviderRecord[]) => {
  return providers.some((provider) => provider.enabled && provider.api_key_configured && Boolean(provider.model?.trim()))
}

const isProviderUnavailableError = (error: unknown) => {
  if (!(error instanceof Error)) {
    return false
  }
  return error.message.includes('LLM Provider') || error.message.includes('未启用可用的 LLM Provider')
}

// 把后端任务对象压成异常页可直接消费的轻量状态，避免页面处处判断原始字段。
const buildRecommendationTaskState = (task: TaskRecord, incidentId: string): RecommendationTaskState => ({
  taskId: task.task_id,
  incidentId,
  taskType: task.task_type,
  status: task.status,
  currentStage: task.current_stage,
  progress: task.progress,
  progressMessage: task.progress_message,
  updatedAt: task.updated_at,
  errorMessage: task.error?.error_message,
  artifactReady: false,
})

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

export const IncidentCenter: React.FC = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetailResponse | null>(null)
  const [serviceKey, setServiceKey] = useState('unknown/root')
  const [creating, setCreating] = useState(false)
  const [generatingRecommendation, setGeneratingRecommendation] = useState(false)
  const [aiSummaryLoading, setAiSummaryLoading] = useState(false)
  const [aiSummary, setAiSummary] = useState<IncidentAISummaryResponse | null>(null)
  const [aiProviderReady, setAiProviderReady] = useState<boolean | null>(null)
  const [aiProviderChecking, setAiProviderChecking] = useState(true)
  const [recommendationTask, setRecommendationTask] = useState<RecommendationTaskState | null>(null)
  const [error, setError] = useState('')

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
            : 'other'
      groups[layer] = groups[layer] || []
      groups[layer].push(item)
    }
    return Object.entries(groups)
      .sort((left, right) => (layerMeta[left[0]]?.order || 99) - (layerMeta[right[0]]?.order || 99))
      .map(([layer, items]) => [layer, sortEvidenceItems(items)] as const)
  }, [selectedIncident])

  const diagnosisSummary = useMemo(() => {
    if (!selectedIncident) {
      return null
    }
    const evidenceItems = (selectedIncident.incident.evidence_refs || []) as EvidenceItem[]
    const diagnosisItem = evidenceItems.find((item) => item.layer === 'diagnosis')
    const topEvidence = sortEvidenceItems(evidenceItems.filter((item) => item.layer !== 'diagnosis')).slice(0, 3)
    return {
      conclusion: selectedIncident.incident.summary,
      nextStep: String(diagnosisItem?.next_step || selectedIncident.incident.recommended_actions[0] || '继续观察关键指标变化'),
      highlights: topEvidence,
    }
  }, [selectedIncident])

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
    const response = (await incidentsApi.get(incidentId)) as IncidentDetailResponse
    setSelectedIncident(response)
    setAiSummary(null)
    return response
  }, [])

  const refreshAIProviderAvailability = useCallback(async () => {
    setAiProviderChecking(true)
    try {
      const payload = (await aiApi.listProviders()) as { providers?: LLMProviderRecord[] }
      setAiProviderReady(hasUsableAIProvider(payload.providers || []))
    } catch {
      // 获取 provider 状态失败时不阻塞页面操作，保持为可尝试状态。
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
      await incidentsApi.analyze({ service_key: serviceKey || undefined, time_window: '1h' })
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

  const openTrafficForIncident = () => {
    if (!selectedIncident) {
      return
    }
    const params = new URLSearchParams()
    const timeWindowStart = new Date(selectedIncident.incident.time_window_start)
    const timeWindowEnd = new Date(selectedIncident.incident.time_window_end)
    const durationMs = Math.max(0, timeWindowEnd.getTime() - timeWindowStart.getTime())
    const hours = durationMs / (1000 * 60 * 60)
    const timeRange = hours > 6 ? '24h' : hours > 1 ? '6h' : '1h'
    params.set('time_range', timeRange)
    params.set('service_key', selectedIncident.incident.service_key)
    navigate(`/traffic?${params.toString()}`)
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
      setRecommendationTask(buildRecommendationTaskState(task, selectedIncident.incident.incident_id))
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

      {error ? <Alert type="error" showIcon message="异常中心加载失败" description={error} style={{ marginBottom: 16 }} /> : null}
      {aiProviderReady === false ? (
        <Alert
          type="warning"
          showIcon
          message="AI 功能未启用"
          description="请先到「LLM 设置」启用可用 Provider，异常总结和 AI 复核入口会在配置后自动恢复。"
          action={<Button type="link" size="small" onClick={() => navigate('/llm-settings')}>前往 LLM 设置</Button>}
          style={{ marginBottom: 16 }}
        />
      ) : null}

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
                <Button onClick={() => openRecommendationCenter()} disabled={!selectedIncident}>
                  打开建议中心
                </Button>
              </Space>
            }
          >
            {!selectedIncident ? (
              <Empty description="请选择一个异常或先发起分析" />
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
                      <div className="ops-incident-brief__highlights">
                        {diagnosisSummary.highlights.length > 0 ? diagnosisSummary.highlights.map((item) => (
                          <div key={`${item.layer}-${item.metric}-${item.title}`} className="ops-incident-brief__highlight">
                            <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                              <Tag color={layerMeta[item.layer || 'other']?.color || layerMeta.other.color}>{layerMeta[item.layer || 'other']?.title || layerMeta.other.title}</Tag>
                              <Text strong>{String(item.title || item.metric || '关键证据')}</Text>
                              <Tag>{formatEvidenceValue(item)}</Tag>
                            </Space>
                            <Paragraph style={{ marginBottom: 0 }}>{String(item.summary || '-')}</Paragraph>
                          </div>
                        )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无高优先证据" />}
                      </div>
                    </div>
                  </Card>
                ) : null}

                {aiSummary ? (
                  <Card type="inner" title="AI 异常总结" style={{ marginBottom: 16 }}>
                    <Space style={{ marginBottom: 12, flexWrap: 'wrap' }}>
                      <Tag color={aiSummary.risk_level === 'high' ? 'red' : aiSummary.risk_level === 'medium' ? 'orange' : 'green'}>
                        风险等级: {aiSummary.risk_level}
                      </Tag>
                      <Tag color="geekblue">AI 置信度: {Math.round(aiSummary.confidence * 100)}%</Tag>
                      <Tag>{aiSummary.parse_mode === 'json' ? '结构化输出' : '降级输出'}</Tag>
                    </Space>
                    <Paragraph style={{ marginBottom: 12, whiteSpace: 'pre-wrap' }}>{aiSummary.summary}</Paragraph>
                    <Text strong style={{ display: 'block', marginBottom: 8 }}>可能原因</Text>
                    <List
                      size="small"
                      dataSource={aiSummary.primary_causes}
                      locale={{ emptyText: '无' }}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                      style={{ marginBottom: 12 }}
                    />
                    <Text strong style={{ display: 'block', marginBottom: 8 }}>建议动作</Text>
                    <List
                      size="small"
                      dataSource={aiSummary.recommended_actions}
                      locale={{ emptyText: '无' }}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                      style={{ marginBottom: 12 }}
                    />
                    <Text strong style={{ display: 'block', marginBottom: 8 }}>证据引用</Text>
                    <List
                      size="small"
                      dataSource={aiSummary.evidence_citations}
                      locale={{ emptyText: '无' }}
                      renderItem={(item) => <List.Item><Text code>{item}</Text></List.Item>}
                    />
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
                            return (
                              <List.Item>
                                <div style={{ width: '100%' }}>
                                  <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                                    <Text strong>{String(item.title || item.name || item.metric || item.type || '证据项')}</Text>
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
    </div>
  )
}

export default IncidentCenter
