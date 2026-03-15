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
import {
  executorsApi,
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

const ExecutorPlugins: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [statusData, setStatusData] = useState<ExecutorStatusResponse | null>(null)
  const [selectedPluginKey, setSelectedPluginKey] = useState('linux')
  const [command, setCommand] = useState('ps aux')
  const [readonly, setReadonly] = useState(true)
  const [operator, setOperator] = useState('operator')
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
                  <Descriptions.Item label="错误码">{runResult.execution.error_code || '-'}</Descriptions.Item>
                  <Descriptions.Item label="错误消息">{runResult.execution.error_message || '-'}</Descriptions.Item>
                  <Descriptions.Item label="标准输出">
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{runResult.execution.stdout_preview || '-'}</pre>
                  </Descriptions.Item>
                  <Descriptions.Item label="标准错误">
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{runResult.execution.stderr_preview || '-'}</pre>
                  </Descriptions.Item>
                </Descriptions>
              </Space>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="审计日志" loading={loading} className="ops-surface-card">
            {!statusData ? (
              <CardEmptyState title="暂无日志" />
            ) : (
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
                    title: '命令',
                    dataIndex: 'command',
                    render: (value: string) => <Text code>{value}</Text>,
                  },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default ExecutorPlugins
