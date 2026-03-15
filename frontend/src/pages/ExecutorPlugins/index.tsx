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
import { useNavigate } from 'react-router-dom'
import {
  executorsApi,
  type ExecutorReadonlyCommandPack,
  type ExecutorFailureDigest,
  type ExecutorPluginStatus,
  type ExecutorRunResponse,
  type ExecutorStatusResponse,
} from '@/api/client'
import { CardEmptyState, PageStatusBanner } from '@/components/PageState'

const { Paragraph, Text, Title } = Typography

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [statusData, setStatusData] = useState<ExecutorStatusResponse | null>(null)
  const [selectedPluginKey, setSelectedPluginKey] = useState('linux')
  const [command, setCommand] = useState('ps aux')
  const [readonly, setReadonly] = useState(true)
  const [operator, setOperator] = useState('operator')
  const [taskId, setTaskId] = useState('')
  const [approvalTicket, setApprovalTicket] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState(20)
  const [runResult, setRunResult] = useState<ExecutorRunResponse | null>(null)

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

  const recentFailures = useMemo<ExecutorFailureDigest[]>(() => {
    // 后端已返回 recent_failures 时直接使用；否则退化为前端基于 recent_logs 的兜底计算。
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

  useEffect(() => {
    void loadStatus()
  }, [])

  // 根据插件切换默认命令，减少误触风险。
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
        operator: operator.trim() || 'operator',
        approval_ticket: approvalTicket.trim() || undefined,
      })) as ExecutorRunResponse
      setRunResult(response)
      const runStatus = response.execution.status
      if (runStatus === 'success') {
        message.success('命令执行成功')
      } else if (runStatus === 'rejected') {
        message.warning('命令已被拦截，请检查白名单或只读设置')
      } else {
        message.error('命令执行失败，请查看审计记录')
      }
      await loadStatus()
    } catch (runError) {
      message.error(runError instanceof Error ? runError.message : '命令执行失败')
    } finally {
      setRunning(false)
    }
  }

  const fillCommandFromPack = (pack: ExecutorReadonlyCommandPack) => {
    // 命令包只提供安全模板，填充时自动切回只读模式，避免误触写操作。
    setCommand(pack.command)
    setReadonly(true)
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

              {groupedReadonlyCommandPacks.length ? (
                <Card size="small" title="只读命令包（可一键填入）">
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
                  description={
                    <>
                      <div>审批拦截 {statusData.summary.approval_required || 0} 次，熔断插件 {statusData.summary.circuit_open_plugins || 0} 个。</div>
                      <div>
                        高频错误：
                        {(statusData.summary.top_error_codes || [])
                          .map((item) => `${item.error_code}(${item.count})`)
                          .join('，') || '暂无'}
                      </div>
                    </>
                  }
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
