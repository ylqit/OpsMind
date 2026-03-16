import React, { useMemo, useState } from 'react'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Col,
  Input,
  List,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  aiApi,
  type AIAssistantCommandSuggestion,
  type AIAssistantDiagnoseResponse,
  type AIAssistantStatusResponse,
} from '@/api/client'
import { CardEmptyState, PageStatusBanner } from '@/components/PageState'
import { useWorkspaceFilterStore } from '@/stores/workspaceFilterStore'

const { Paragraph, Text, Title } = Typography

const timeRangeOptions = [
  { label: '最近 1 小时', value: '1h' },
  { label: '最近 6 小时', value: '6h' },
  { label: '最近 24 小时', value: '24h' },
]

const quickPrompts = [
  '入口 5xx 上升时，优先排查什么？',
  '容器重启频繁时，如何只读定位根因？',
  'CPU 飙高但流量平稳，下一步该看哪些证据？',
]

interface AssistantConversationItem {
  id: string
  role: 'user' | 'assistant'
  content: string
  status?: 'success' | 'degraded'
  provider?: string
  latencyMs?: number
  degradedReason?: string
  suggestions?: AIAssistantCommandSuggestion[]
}

const groupSuggestions = (items: AIAssistantCommandSuggestion[]) => {
  const grouped = new Map<string, { label: string; items: AIAssistantCommandSuggestion[] }>()
  for (const item of items) {
    const key = item.category_key || 'general'
    const label = item.category_label || '通用'
    if (!grouped.has(key)) {
      grouped.set(key, { label, items: [] })
    }
    grouped.get(key)?.items.push(item)
  }
  return Array.from(grouped.entries()).map(([key, value]) => ({ key, ...value }))
}

const AIAssistantWorkbench: React.FC = () => {
  const timeRange = useWorkspaceFilterStore((state) => state.timeRange)
  const serviceKey = useWorkspaceFilterStore((state) => state.serviceKey)
  const setTimeRange = useWorkspaceFilterStore((state) => state.setTimeRange)
  const setServiceKey = useWorkspaceFilterStore((state) => state.setServiceKey)

  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState('')
  const [statusPayload, setStatusPayload] = useState<AIAssistantStatusResponse | null>(null)
  const [diagnoseLoading, setDiagnoseLoading] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [history, setHistory] = useState<AssistantConversationItem[]>([])

  const serviceOptions = useMemo(
    () => {
      const values = new Set<string>()
      if (serviceKey) {
        values.add(serviceKey)
      }
      return Array.from(values).map((item) => ({ value: item, label: item }))
    },
    [serviceKey],
  )

  const latestAssistantItem = useMemo(
    () => [...history].reverse().find((item) => item.role === 'assistant'),
    [history],
  )

  const activeSuggestions = latestAssistantItem?.suggestions?.length
    ? latestAssistantItem.suggestions
    : (statusPayload?.command_suggestions || [])

  const groupedSuggestions = useMemo(() => groupSuggestions(activeSuggestions), [activeSuggestions])

  const loadAssistantStatus = async () => {
    setStatusLoading(true)
    setStatusError('')
    try {
      const response = (await aiApi.getAssistantStatus()) as AIAssistantStatusResponse
      setStatusPayload(response)
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : 'AI 助手状态获取失败')
    } finally {
      setStatusLoading(false)
    }
  }

  React.useEffect(() => {
    void loadAssistantStatus()
  }, [])

  const copyText = async (value: string, successText: string) => {
    try {
      await navigator.clipboard.writeText(value)
      message.success(successText)
    } catch {
      message.error('复制失败，请手动复制')
    }
  }

  const runDiagnose = async () => {
    const normalizedPrompt = prompt.trim()
    if (!normalizedPrompt) {
      message.warning('请先输入诊断问题')
      return
    }
    const userItem: AssistantConversationItem = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: normalizedPrompt,
    }
    setHistory((previous) => [...previous, userItem])
    setDiagnoseLoading(true)
    try {
      const response = (await aiApi.diagnoseWithAssistant({
        message: normalizedPrompt,
        service_key: serviceKey || undefined,
        time_range: timeRange,
        include_command_packs: true,
      })) as AIAssistantDiagnoseResponse
      const assistantItem: AssistantConversationItem = {
        id: `assistant_${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        status: response.status,
        provider: response.provider,
        latencyMs: response.latency_ms,
        degradedReason: response.degraded_reason,
        suggestions: response.command_suggestions || [],
      }
      setHistory((previous) => [...previous, assistantItem])
      if (response.status === 'degraded') {
        message.warning('AI 助手已降级到规则模式，建议先完成 Provider 配置')
      }
      setPrompt('')
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'AI 助手诊断失败')
    } finally {
      setDiagnoseLoading(false)
    }
  }

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>AI 助手工作台</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            提供对话式只读诊断入口，结合当前服务与时间窗给出结论、证据和下一步建议，不替代现有主分析页面。
          </Paragraph>
        </div>
        <Space wrap>
          <Select value={timeRange} onChange={setTimeRange} options={timeRangeOptions} style={{ width: 140 }} />
          <AutoComplete
            value={serviceKey}
            options={serviceOptions}
            onChange={setServiceKey}
            placeholder="输入 service_key（可选）"
            style={{ width: 240 }}
            filterOption={(inputValue, option) => String(option?.value || '').toLowerCase().includes(inputValue.toLowerCase())}
          />
          <Button onClick={() => void loadAssistantStatus()} loading={statusLoading}>刷新状态</Button>
        </Space>
      </div>

      {statusError ? (
        <PageStatusBanner
          type="error"
          title="AI 助手状态加载失败"
          description={statusError}
          actionText="重试"
          onAction={() => void loadAssistantStatus()}
        />
      ) : null}

      {statusPayload && !statusPayload.provider_ready ? (
        <Alert
          type="warning"
          showIcon
          message="当前未检测到可用 AI Provider"
          description={statusPayload.degraded_reason || '工作台会自动降级为规则模式，仍可给出只读排查建议。'}
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="对话诊断" className="ops-surface-card">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Space wrap>
                <Tag color="blue">时间窗：{timeRange}</Tag>
                <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || '全部'}</Tag>
                <Tag color={statusPayload?.provider_ready ? 'green' : 'gold'}>
                  Provider：{statusPayload?.provider_ready ? (statusPayload.default_provider || '已可用') : '降级模式'}
                </Tag>
              </Space>
              <Space wrap>
                {quickPrompts.map((item) => (
                  <Button key={item} size="small" onClick={() => setPrompt(item)}>{item}</Button>
                ))}
              </Space>
              <Input.TextArea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                autoSize={{ minRows: 4, maxRows: 8 }}
                placeholder="请输入你的诊断问题，例如：入口 5xx 上升，先看哪些证据与只读命令？"
              />
              <Space>
                <Button type="primary" loading={diagnoseLoading} onClick={() => void runDiagnose()}>
                  发起诊断
                </Button>
                <Button onClick={() => setPrompt('')}>清空输入</Button>
              </Space>
            </Space>
          </Card>

          <Card title="对话记录" className="ops-surface-card" style={{ marginTop: 16 }}>
            <List
              dataSource={history}
              locale={{ emptyText: <CardEmptyState title="暂无对话记录" description="发起一次诊断后会展示结果。" /> }}
              renderItem={(item) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <Space style={{ marginBottom: 8 }}>
                      <Tag color={item.role === 'user' ? 'blue' : 'green'}>{item.role === 'user' ? '你' : 'AI 助手'}</Tag>
                      {item.status ? (
                        <Tag color={item.status === 'success' ? 'green' : 'gold'}>{item.status}</Tag>
                      ) : null}
                      {item.provider ? <Tag>{item.provider}</Tag> : null}
                      {item.latencyMs != null ? <Tag>{item.latencyMs} ms</Tag> : null}
                    </Space>
                    <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 8 }}>{item.content}</Paragraph>
                    {item.degradedReason ? <Text type="secondary">降级原因：{item.degradedReason}</Text> : null}
                    {item.role === 'assistant' ? (
                      <div style={{ marginTop: 8 }}>
                        <Button size="small" onClick={() => void copyText(item.content, '已复制诊断结果')}>
                          复制结果
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="只读命令建议" className="ops-surface-card">
            <List
              dataSource={groupedSuggestions}
              locale={{ emptyText: <CardEmptyState title="暂无命令建议" description="发起诊断或刷新状态后会显示命令模板。" /> }}
              renderItem={(group) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <Space style={{ marginBottom: 8 }}>
                      <Tag color="cyan">{group.label}</Tag>
                      <Text type="secondary">{group.items.length} 条</Text>
                    </Space>
                    <Space direction="vertical" style={{ width: '100%' }} size={8}>
                      {group.items.map((item) => (
                        <Card key={`${item.plugin_key}_${item.template_id}`} size="small">
                          <Space direction="vertical" style={{ width: '100%' }} size={6}>
                            <Space wrap>
                              <Text strong>{item.title}</Text>
                              <Tag>{item.plugin_name}</Tag>
                            </Space>
                            <Text type="secondary">{item.description || '只读命令模板'}</Text>
                            <Text code style={{ whiteSpace: 'pre-wrap' }}>{item.command}</Text>
                            <Button size="small" onClick={() => void copyText(item.command, '已复制命令')}>
                              复制命令
                            </Button>
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default AIAssistantWorkbench
