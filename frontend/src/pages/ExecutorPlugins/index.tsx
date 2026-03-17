import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  executorsApi,
  type ExecutorFailureDigest,
  type ExecutorPluginStatus,
  type ExecutorReadonlyCommandPack,
  type ExecutorRecommendedCommandGroup,
  type ExecutorRecommendedCommandPack,
  type ExecutorRecommendedCommandPackResponse,
  type ExecutorRunResponse,
  type ExecutorStatusResponse,
} from '@/api/client'
import { CardEmptyState, PageStatusBanner } from '@/components/PageState'

const { Paragraph, Text, Title } = Typography

interface ExecutorWorkbenchEntryContext {
  sessionId: string
  incidentId: string
  recommendationId: string
  serviceKey: string
  timeRange: string
  pluginKey: string
  command: string
  evidenceIds: string[]
  executorResultIds: string[]
}

const statusColorMap: Record<string, string> = {
  healthy: 'green',
  degraded: 'orange',
  disabled: 'default',
}

const runStatusColorMap: Record<string, string> = {
  success: 'green',
  error: 'red',
  timeout: 'orange',
  rejected: 'gold',
  circuit_open: 'purple',
}

const parseDelimitedIds = (value: string) => value
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean)

const stringifyDelimitedIds = (values: string[]) => values.join(',')

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

const summarizeText = (value?: string | null, maxChars = 120) => {
  const normalized = (value || '').trim()
  if (!normalized) {
    return '-'
  }
  const firstLine = normalized.split('\n').find((line) => line.trim())?.trim() || normalized
  if (firstLine.length <= maxChars) {
    return firstLine
  }
  return `${firstLine.slice(0, Math.max(1, maxChars - 3))}...`
}

const ExecutorPlugins: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const entryContext = useMemo<ExecutorWorkbenchEntryContext>(() => ({
    sessionId: (searchParams.get('sessionId') || '').trim(),
    incidentId: (searchParams.get('incidentId') || '').trim(),
    recommendationId: (searchParams.get('recommendationId') || '').trim(),
    serviceKey: (searchParams.get('service_key') || '').trim(),
    timeRange: (searchParams.get('time_range') || '').trim() || '1h',
    pluginKey: (searchParams.get('plugin_key') || '').trim(),
    command: (searchParams.get('command') || '').trim(),
    evidenceIds: parseDelimitedIds((searchParams.get('evidenceIds') || '').trim()),
    executorResultIds: parseDelimitedIds((searchParams.get('executorResultIds') || '').trim()),
  }), [searchParams])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [recommendLoading, setRecommendLoading] = useState(false)
  const [recommendError, setRecommendError] = useState('')
  const [statusData, setStatusData] = useState<ExecutorStatusResponse | null>(null)
  const [recommendedPayload, setRecommendedPayload] = useState<ExecutorRecommendedCommandPackResponse | null>(null)
  const [selectedPluginKey, setSelectedPluginKey] = useState('linux')
  const [command, setCommand] = useState('ps aux')
  const [readonly, setReadonly] = useState(true)
  const [operator, setOperator] = useState('operator')
  const [taskId, setTaskId] = useState('')
  const [approvalTicket, setApprovalTicket] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState(20)
  const [runResult, setRunResult] = useState<ExecutorRunResponse | null>(null)

  const hasRecommendationContext = Boolean(
    entryContext.sessionId
      || entryContext.incidentId
      || entryContext.recommendationId
      || entryContext.serviceKey,
  )

  const selectedPlugin = useMemo(
    () => statusData?.plugins.find((item) => item.plugin_key === selectedPluginKey) || null,
    [statusData, selectedPluginKey],
  )

  const pluginOptions = useMemo(
    () => (statusData?.plugins || []).map((item) => ({ label: item.display_name, value: item.plugin_key })),
    [statusData],
  )

  const groupedReadonlyCommandPacks = useMemo(() => {
    if (!selectedPlugin?.readonly_command_packs?.length) {
      return []
    }
    const grouped = new Map<string, { categoryKey: string; categoryLabel: string; items: ExecutorReadonlyCommandPack[] }>()
    for (const item of selectedPlugin.readonly_command_packs) {
      const current = grouped.get(item.category_key)
      if (current) {
        current.items.push(item)
        continue
      }
      grouped.set(item.category_key, {
        categoryKey: item.category_key,
        categoryLabel: item.category_label,
        items: [item],
      })
    }
    return Array.from(grouped.values())
  }, [selectedPlugin])

  const recommendedGroups = useMemo<ExecutorRecommendedCommandGroup[]>(
    () => recommendedPayload?.items || [],
    [recommendedPayload],
  )

  const activeSessionId = useMemo(
    () => (recommendedPayload?.context.session_id || entryContext.sessionId || '').trim(),
    [entryContext.sessionId, recommendedPayload?.context.session_id],
  )

  const activeExecutorResultIds = useMemo(
    () => (
      recommendedPayload?.context.executor_result_ids?.length
        ? recommendedPayload.context.executor_result_ids
        : entryContext.executorResultIds
    ),
    [entryContext.executorResultIds, recommendedPayload?.context.executor_result_ids],
  )

  const recentFailures = useMemo<ExecutorFailureDigest[]>(() => {
    if (statusData?.recent_failures?.length) {
      return statusData.recent_failures
    }
    return (statusData?.recent_logs || [])
      .filter((item) => item.status !== 'success')
      .slice(0, 8)
      .map((item) => ({
        ...item,
        stderr_summary: summarizeText(item.stderr_preview || item.error_message || '-'),
        approval_required: item.error_code === 'EXECUTOR_APPROVAL_REQUIRED',
        has_approval_ticket: Boolean(item.approval_ticket),
      }))
  }, [statusData])

  const statusSummary = useMemo(() => {
    const summary = statusData?.summary
    if (!summary) {
      return '暂无执行统计'
    }
    const success = summary.success || 0
    const error = summary.error || 0
    const timeout = summary.timeout || 0
    const rejected = summary.rejected || 0
    const circuitOpen = summary.circuit_open || 0
    return `成功 ${success}，失败 ${error}，超时 ${timeout}，拦截 ${rejected}，熔断 ${circuitOpen}`
  }, [statusData])

  const loadStatus = async () => {
    setLoading(true)
    setError('')
    try {
      const response = (await executorsApi.getStatus({ limit: 30 })) as ExecutorStatusResponse
      setStatusData(response)
      if (response.plugins.length > 0 && !response.plugins.some((item) => item.plugin_key === selectedPluginKey)) {
        setSelectedPluginKey(response.plugins[0].plugin_key)
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '执行插件状态加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadRecommendedCommandPacks = async () => {
    if (!hasRecommendationContext) {
      setRecommendedPayload(null)
      setRecommendError('')
      return
    }
    setRecommendLoading(true)
    setRecommendError('')
    try {
      const response = (await executorsApi.getRecommendedCommandPacks({
        session_id: entryContext.sessionId || undefined,
        incident_id: entryContext.incidentId || undefined,
        recommendation_id: entryContext.recommendationId || undefined,
        limit: 8,
      })) as ExecutorRecommendedCommandPackResponse
      setRecommendedPayload(response)
    } catch (loadError) {
      setRecommendError(loadError instanceof Error ? loadError.message : '推荐命令包加载失败')
      setRecommendedPayload(null)
    } finally {
      setRecommendLoading(false)
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  useEffect(() => {
    void loadRecommendedCommandPacks()
  }, [
    entryContext.incidentId,
    entryContext.recommendationId,
    entryContext.serviceKey,
    entryContext.sessionId,
    entryContext.timeRange,
    hasRecommendationContext,
  ])

  useEffect(() => {
    if (entryContext.pluginKey) {
      setSelectedPluginKey(entryContext.pluginKey)
    }
    if (entryContext.command) {
      // 从 AI 助手或异常链路带入命令时，优先填充为只读模板执行。
      setCommand(entryContext.command)
      setReadonly(true)
    }
  }, [entryContext.command, entryContext.pluginKey])

  useEffect(() => {
    if (!selectedPlugin) {
      return
    }
    const firstExample = selectedPlugin.readonly_examples[0]
    if (firstExample && !command.trim()) {
      setCommand(firstExample)
    }
  }, [selectedPlugin, command])

  const patchPlugin = async (plugin: ExecutorPluginStatus, updates: { enabled?: boolean; write_enabled?: boolean }) => {
    try {
      await executorsApi.patchPlugin(plugin.plugin_key, {
        ...updates,
        approval_ticket: approvalTicket.trim() || undefined,
      })
      message.success('插件配置已更新')
      await loadStatus()
    } catch (patchError) {
      message.error(patchError instanceof Error ? patchError.message : '插件配置更新失败')
    }
  }

  const fillCommandFromPack = (
    pack: ExecutorReadonlyCommandPack | ExecutorRecommendedCommandPack,
    pluginKey = selectedPluginKey,
  ) => {
    // 命令包只提供安全模板，填充时自动切回只读模式，避免误触写操作。
    setSelectedPluginKey(pluginKey)
    setCommand(pack.command)
    setReadonly(true)
  }

  const buildAssistantSearchParams = (executorResultIds: string[]) => {
    const params = new URLSearchParams()
    if (activeSessionId) {
      params.set('sessionId', activeSessionId)
    }
    if (entryContext.incidentId) {
      params.set('incidentId', entryContext.incidentId)
      params.set('source', 'incident')
    }
    if (entryContext.recommendationId) {
      params.set('recommendationId', entryContext.recommendationId)
      params.set('source', 'recommendation')
    }
    const serviceKey = recommendedPayload?.context.service_key || entryContext.serviceKey
    if (serviceKey) {
      params.set('service_key', serviceKey)
    }
    const timeRange = recommendedPayload?.context.time_range || entryContext.timeRange
    if (timeRange) {
      params.set('time_range', timeRange)
    }
    if (entryContext.evidenceIds.length) {
      params.set('evidenceIds', stringifyDelimitedIds(entryContext.evidenceIds))
    }
    if (executorResultIds.length) {
      params.set('executorResultIds', stringifyDelimitedIds(executorResultIds))
    }
    return params
  }

  const openAssistantWorkbench = () => {
    const params = buildAssistantSearchParams(activeExecutorResultIds)
    navigate(`/assistant${params.toString() ? `?${params.toString()}` : ''}`)
  }

  const runCommand = async () => {
    if (!selectedPlugin) {
      message.warning('请先选择插件')
      return
    }
    if (!command.trim()) {
      message.warning('请输入命令')
      return
    }
    if (!readonly && !approvalTicket.trim()) {
      message.warning('非只读执行需要填写 approval_ticket')
      return
    }

    setRunning(true)
    try {
      const response = (await executorsApi.run({
        plugin_key: selectedPlugin.plugin_key,
        command: command.trim(),
        readonly,
        timeout_seconds: timeoutSeconds,
        task_id: taskId.trim() || undefined,
        session_id: activeSessionId || undefined,
        operator: operator.trim() || 'operator',
        approval_ticket: approvalTicket.trim() || undefined,
      })) as ExecutorRunResponse
      setRunResult(response)
      const runStatus = response.execution.status
      const linkedSessionIds = response.analysis_session?.executor_result_ids || activeExecutorResultIds
      if (response.analysis_session?.linked) {
        const nextParams = buildAssistantSearchParams(linkedSessionIds)
        nextParams.set('plugin_key', selectedPlugin.plugin_key)
        nextParams.set('command', command.trim())
        setSearchParams(nextParams, { replace: true })
        setRecommendedPayload((previous) => (
          previous
            ? {
                ...previous,
                context: {
                  ...previous.context,
                  session_id: response.analysis_session?.session_id || previous.context.session_id,
                  executor_result_ids: linkedSessionIds,
                  service_key: response.analysis_session?.service_key || previous.context.service_key,
                  time_range: response.analysis_session?.time_range || previous.context.time_range,
                },
              }
            : previous
        ))
      }
      if (runStatus === 'success') {
        message.success(
          response.analysis_session?.linked
            ? '命令执行成功，结果已回流到当前分析会话'
            : '命令执行成功',
        )
      } else if (runStatus === 'rejected') {
        message.warning('命令已被拦截，请检查白名单或只读设置')
      } else {
        message.error('命令执行失败，请查看审计记录')
      }
      await Promise.all([loadStatus(), loadRecommendedCommandPacks()])
    } catch (runError) {
      message.error(runError instanceof Error ? runError.message : '命令执行失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>执行插件</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            Linux / K8s / Docker 三类插件统一纳管，默认只读白名单执行，具备超时、熔断和审计追踪能力。
          </Paragraph>
        </div>
        <Space>
          {hasRecommendationContext ? (
            <Button onClick={openAssistantWorkbench}>返回 AI 助手</Button>
          ) : null}
          <Button onClick={() => void loadStatus()}>刷新</Button>
        </Space>
      </div>

      {error ? (
        <PageStatusBanner
          type="error"
          title="执行插件状态加载失败"
          description={error}
          actionText="重新加载"
          onAction={() => void loadStatus()}
        />
      ) : null}

      {hasRecommendationContext ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前页面已接管分析上下文，可直接做补证执行"
          description={(
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              <Space wrap>
                {activeSessionId ? <Tag color="cyan">session：{activeSessionId}</Tag> : null}
                {entryContext.incidentId ? <Tag>incident：{entryContext.incidentId}</Tag> : null}
                {entryContext.recommendationId ? <Tag color="purple">recommendation：{entryContext.recommendationId}</Tag> : null}
                <Tag color={(recommendedPayload?.context.service_key || entryContext.serviceKey) ? 'geekblue' : 'default'}>
                  服务：{recommendedPayload?.context.service_key || entryContext.serviceKey || '全部'}
                </Tag>
                <Tag>时间窗：{recommendedPayload?.context.time_range || entryContext.timeRange || '1h'}</Tag>
                {activeExecutorResultIds.length ? <Tag color="orange">已有执行结果 {activeExecutorResultIds.length}</Tag> : null}
              </Space>
              {recommendedPayload?.context.signals?.length ? (
                <Text type="secondary">推荐依据：{recommendedPayload.context.signals.join('；')}</Text>
              ) : (
                <Text type="secondary">当前会话已自动带入异常 / 建议上下文，执行结果会继续回流到分析会话。</Text>
              )}
            </Space>
          )}
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="插件状态" loading={loading} className="ops-surface-card">
            {!statusData || statusData.plugins.length === 0 ? (
              <CardEmptyState title="暂无插件数据" description="当前还没有可展示的执行插件状态" />
            ) : (
              <Table
                size="small"
                rowKey="plugin_key"
                pagination={false}
                dataSource={statusData.plugins}
                columns={[
                  {
                    title: '插件',
                    dataIndex: 'display_name',
                    render: (_: string, record: ExecutorPluginStatus) => (
                      <Space direction="vertical" size={2}>
                        <Text strong>{record.display_name}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{record.plugin_key}</Text>
                      </Space>
                    ),
                  },
                  {
                    title: '健康',
                    dataIndex: 'health_status',
                    render: (value: string, record: ExecutorPluginStatus) => (
                      <Space direction="vertical" size={2}>
                        <Tag color={statusColorMap[value] || 'default'}>{value}</Tag>
                        {record.circuit_remaining_seconds > 0 ? (
                          <Text type="secondary" style={{ fontSize: 12 }}>熔断剩余 {record.circuit_remaining_seconds}s</Text>
                        ) : null}
                      </Space>
                    ),
                  },
                  {
                    title: '失败信息',
                    dataIndex: 'last_error',
                    render: (_: string, record: ExecutorPluginStatus) => (
                      <Space direction="vertical" size={2}>
                        <Text type="secondary" style={{ fontSize: 12 }}>失败次数 {record.failure_count}</Text>
                        <Text style={{ fontSize: 12 }}>{summarizeText(record.last_error || '-')}</Text>
                      </Space>
                    ),
                  },
                  {
                    title: '启停',
                    dataIndex: 'enabled',
                    render: (value: boolean, record: ExecutorPluginStatus) => (
                      <Switch
                        checked={value}
                        onChange={(checked) => void patchPlugin(record, { enabled: checked })}
                      />
                    ),
                  },
                  {
                    title: '写入口',
                    dataIndex: 'write_enabled',
                    render: (value: boolean, record: ExecutorPluginStatus) => (
                      <Switch
                        checked={value}
                        onChange={(checked) => void patchPlugin(record, { write_enabled: checked })}
                      />
                    ),
                  },
                ]}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="命令执行" className="ops-surface-card">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="插件选择">
                  <Select
                    value={selectedPluginKey}
                    options={pluginOptions}
                    onChange={setSelectedPluginKey}
                    placeholder="请选择插件"
                    style={{ width: '100%' }}
                  />
                </Descriptions.Item>
                <Descriptions.Item label="执行模式">
                  <Space>
                    <Switch checked={readonly} onChange={setReadonly} />
                    <Tag color={readonly ? 'green' : 'orange'}>{readonly ? '只读执行' : '写操作'}</Tag>
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="超时（秒）">
                  <InputNumber
                    min={1}
                    max={120}
                    value={timeoutSeconds}
                    onChange={(value) => setTimeoutSeconds(Number(value || 20))}
                  />
                </Descriptions.Item>
                <Descriptions.Item label="操作人">
                  <Input value={operator} onChange={(event) => setOperator(event.target.value)} placeholder="operator" />
                </Descriptions.Item>
                <Descriptions.Item label="关联任务 ID">
                  <Input
                    value={taskId}
                    onChange={(event) => setTaskId(event.target.value)}
                    placeholder="可选，填写后会把执行记录挂到任务证据链"
                  />
                </Descriptions.Item>
                <Descriptions.Item label="分析会话">
                  <Text copyable={Boolean(activeSessionId)}>{activeSessionId || '-'}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="审批单">
                  <Input
                    value={approvalTicket}
                    onChange={(event) => setApprovalTicket(event.target.value)}
                    placeholder="写操作必填，例如 SEC-2026-001"
                  />
                </Descriptions.Item>
              </Descriptions>

              <Input.TextArea
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                autoSize={{ minRows: 3, maxRows: 6 }}
                placeholder="输入命令，例如 kubectl get pods -A"
              />

              {hasRecommendationContext ? (
                <Card
                  size="small"
                  title="推荐命令包"
                  loading={recommendLoading}
                  extra={recommendedPayload ? <Tag color="blue">{recommendedPayload.recommended_total} 条推荐</Tag> : null}
                >
                  {recommendError ? (
                    <Alert type="warning" showIcon message="推荐命令包加载失败" description={recommendError} />
                  ) : recommendedGroups.length ? (
                    <Space direction="vertical" style={{ width: '100%' }} size={10}>
                      {recommendedGroups.map((group) => (
                        <div key={group.plugin_key}>
                          <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                            <Tag color="purple">{group.display_name}</Tag>
                            <Tag color="gold">优先级 {group.priority}</Tag>
                            <Text type="secondary">{group.reason}</Text>
                          </Space>
                          <Space direction="vertical" style={{ width: '100%' }} size={8}>
                            {group.recommended_command_packs.map((item) => (
                              <Card key={`${group.plugin_key}_${item.template_id}`} size="small">
                                <Space direction="vertical" style={{ width: '100%' }} size={6}>
                                  <Space wrap>
                                    <Text strong>{item.title}</Text>
                                    <Tag color="blue">{item.category_label}</Tag>
                                    <Tag>评分 {item.score}</Tag>
                                    {item.already_executed ? <Tag color="default">已执行过</Tag> : null}
                                  </Space>
                                  <Text type="secondary">{item.description}</Text>
                                  <Text type="secondary">{item.reason}</Text>
                                  <Text code style={{ whiteSpace: 'pre-wrap' }}>{item.command}</Text>
                                  <Space wrap>
                                    <Button size="small" type="primary" onClick={() => fillCommandFromPack(item, group.plugin_key)}>
                                      填入命令
                                    </Button>
                                  </Space>
                                </Space>
                              </Card>
                            ))}
                          </Space>
                        </div>
                      ))}
                    </Space>
                  ) : (
                    <CardEmptyState
                      title="暂无推荐命令包"
                      description="当前上下文还没有形成明确的补证命令推荐，可继续使用下方通用只读命令包。"
                    />
                  )}
                </Card>
              ) : null}

              {groupedReadonlyCommandPacks.length ? (
                <Card size="small" title="通用只读命令包（可一键填入）">
                  <Space direction="vertical" style={{ width: '100%' }} size={10}>
                    {groupedReadonlyCommandPacks.map((group) => (
                      <div key={group.categoryKey}>
                        <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                          <Tag color="blue">{group.categoryLabel}</Tag>
                          <Text type="secondary">{group.items.length} 条模板</Text>
                        </Space>
                        <Space wrap>
                          {group.items.map((item) => (
                            <Button key={item.template_id} size="small" onClick={() => fillCommandFromPack(item)}>
                              {item.title}
                            </Button>
                          ))}
                        </Space>
                      </div>
                    ))}
                  </Space>
                </Card>
              ) : null}

              <Button type="primary" onClick={() => void runCommand()} loading={running}>
                执行命令
              </Button>

              {selectedPlugin ? (
                <Alert
                  type={selectedPlugin.enabled ? 'info' : 'warning'}
                  showIcon
                  message={`${selectedPlugin.display_name}：${selectedPlugin.description}`}
                  description={(
                    <Space direction="vertical" size={4}>
                      <Text type="secondary">只读示例：{selectedPlugin.readonly_examples.join(' | ') || '-'}</Text>
                      <Text type="secondary">写入示例：{selectedPlugin.write_examples.join(' | ') || '-'}</Text>
                    </Space>
                  )}
                />
              ) : (
                <CardEmptyState title="请先选择插件" description="选择一个执行插件后再输入命令" />
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="最近执行结果" className="ops-surface-card">
            {!runResult ? (
              <CardEmptyState title="尚未执行命令" description="执行一次命令后会在这里展示结果摘要" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Space wrap>
                  <Tag color={runStatusColorMap[runResult.execution.status] || 'default'}>{runResult.execution.status}</Tag>
                  <Tag>{runResult.execution.plugin_key}</Tag>
                  <Tag>{runResult.execution.duration_ms} ms</Tag>
                  <Tag>{runResult.execution.readonly ? 'readonly' : 'write'}</Tag>
                </Space>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="命令">{runResult.execution.command}</Descriptions.Item>
                  <Descriptions.Item label="审批单">{runResult.execution.approval_ticket || '-'}</Descriptions.Item>
                  <Descriptions.Item label="错误码">{runResult.execution.error_code || '-'}</Descriptions.Item>
                  <Descriptions.Item label="错误消息">{runResult.execution.error_message || '-'}</Descriptions.Item>
                  <Descriptions.Item label="标准输出">
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{runResult.execution.stdout_preview || '-'}</pre>
                  </Descriptions.Item>
                  <Descriptions.Item label="标准错误">
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{runResult.execution.stderr_preview || '-'}</pre>
                  </Descriptions.Item>
                </Descriptions>
                {runResult.execution.status === 'circuit_open' ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={`插件处于熔断状态，预计 ${runResult.plugin.circuit_remaining_seconds}s 后恢复`}
                    description={summarizeText(runResult.plugin.last_error || runResult.execution.error_message || '-')}
                  />
                ) : null}
                {runResult.execution.error_code === 'EXECUTOR_APPROVAL_REQUIRED' ? (
                  <Alert
                    type="info"
                    showIcon
                    message="写操作缺少审批单"
                    description="本次命令已被拦截，请补充审批单后重试。"
                  />
                ) : null}
                {runResult.analysis_session ? (
                  <Alert
                    type={runResult.analysis_session.linked ? 'success' : 'info'}
                    showIcon
                    message={
                      runResult.analysis_session.linked
                        ? '执行结果已回流到当前分析会话'
                        : `分析会话未挂载：${runResult.analysis_session.reason || 'unknown'}`
                    }
                    description={
                      runResult.analysis_session.linked
                        ? `会话 ${runResult.analysis_session.session_id}，当前累计 ${runResult.analysis_session.executor_result_ids?.length || 0} 条执行结果`
                        : '本次执行不会影响当前 AI 会话上下文。'
                    }
                    action={runResult.analysis_session.linked ? (
                      <Button size="small" onClick={openAssistantWorkbench}>
                        返回 AI 助手
                      </Button>
                    ) : undefined}
                  />
                ) : null}
                {runResult.task_evidence ? (
                  // 任务挂链结果单独展示，避免用户误以为执行成功就一定写入了任务证据链。
                  <Alert
                    type={runResult.task_evidence.linked ? 'success' : 'info'}
                    showIcon
                    message={
                      runResult.task_evidence.linked
                        ? '执行记录已挂载到任务证据链'
                        : `任务证据链未挂载：${runResult.task_evidence.reason || 'unknown'}`
                    }
                    description={
                      runResult.task_evidence.linked
                        ? `任务 ${runResult.task_evidence.task_id}，产物 ${runResult.task_evidence.artifact_id}`
                        : runResult.task_evidence.message || '本次执行仅记录在插件审计日志中'
                    }
                    action={
                      runResult.task_evidence.task_id ? (
                        <Button
                          size="small"
                          onClick={() => navigate(`/tasks?taskId=${encodeURIComponent(runResult.task_evidence?.task_id || '')}`)}
                        >
                          打开任务中心
                        </Button>
                      ) : undefined
                    }
                  />
                ) : null}
              </Space>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="审计日志" loading={loading} className="ops-surface-card">
            {!statusData ? (
              <CardEmptyState title="暂无日志" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Alert
                  type={recentFailures.length > 0 ? 'warning' : 'success'}
                  showIcon
                  message={statusSummary}
                  description={(
                    <>
                      <div>审批拦截 {statusData.summary.approval_required || 0} 次，熔断插件 {statusData.summary.circuit_open_plugins || 0} 个。</div>
                      <div>
                        高频错误：
                        {(statusData.summary.top_error_codes || [])
                          .map((item) => `${item.error_code}(${item.count})`)
                          .join('，') || '暂无'}
                      </div>
                    </>
                  )}
                />
                <Table
                  size="small"
                  rowKey="execution_id"
                  pagination={false}
                  dataSource={statusData.recent_logs}
                  locale={{ emptyText: <CardEmptyState title="暂无审计日志" /> }}
                  columns={[
                    {
                      title: '时间',
                      dataIndex: 'created_at',
                      width: 170,
                      render: (value: string) => formatDateTime(value),
                    },
                    {
                      title: '插件',
                      dataIndex: 'plugin_key',
                      width: 90,
                      render: (value: string) => <Tag>{value}</Tag>,
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 120,
                      render: (value: string) => <Tag color={runStatusColorMap[value] || 'default'}>{value}</Tag>,
                    },
                    {
                      title: '审批单',
                      dataIndex: 'approval_ticket',
                      width: 140,
                      render: (value: string) => (value ? <Tag color="blue">{value}</Tag> : <Text type="secondary">-</Text>),
                    },
                    {
                      title: 'stderr 摘要',
                      key: 'stderr_summary',
                      render: (_: unknown, record: ExecutorFailureDigest) => (
                        <Text>{summarizeText(record.stderr_summary || record.stderr_preview || record.error_message || '-')}</Text>
                      ),
                    },
                    {
                      title: '命令',
                      dataIndex: 'command',
                      render: (value: string) => <Text code>{value}</Text>,
                    },
                  ]}
                />
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default ExecutorPlugins
