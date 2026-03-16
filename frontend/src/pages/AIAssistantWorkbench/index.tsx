import React, { useEffect, useMemo, useState } from 'react'
import {
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
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  aiApi,
  type AIAssistantCommandSuggestion,
  type AIAssistantDiagnoseResponse,
  type AIAssistantStatusResponse,
} from '@/api/client'
import AIProviderStatusStrip from '@/components/ai/AIProviderStatusStrip'
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

interface AssistantEntryContext {
  source: 'manual' | 'incident' | 'recommendation'
  incidentId: string
  recommendationId: string
  prompt: string
  serviceKey: string
  timeRange: '1h' | '6h' | '24h'
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

const getContextLabel = (source: AssistantEntryContext['source']) => {
  if (source === 'incident') {
    return '来自异常中心'
  }
  if (source === 'recommendation') {
    return '来自建议中心'
  }
  return '手动进入'
}

const getStatusLabel = (status?: AIAssistantStatusResponse['status']) => {
  if (status === 'ready') {
    return '已就绪'
  }
  if (status === 'degraded') {
    return '降级中'
  }
  if (status === 'unavailable') {
    return '不可用'
  }
  return '未知'
}

const AIAssistantWorkbench: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
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

  const entryContext = useMemo<AssistantEntryContext>(() => {
    const sourceValue = (searchParams.get('source') || '').trim()
    return {
      source: sourceValue === 'incident' || sourceValue === 'recommendation' ? sourceValue : 'manual',
      incidentId: (searchParams.get('incidentId') || '').trim(),
      recommendationId: (searchParams.get('recommendationId') || '').trim(),
      prompt: (searchParams.get('prompt') || '').trim(),
      serviceKey: (searchParams.get('service_key') || '').trim(),
      timeRange: (searchParams.get('time_range') || '').trim() === '24h'
        ? '24h'
        : (searchParams.get('time_range') || '').trim() === '6h'
          ? '6h'
          : '1h',
    }
  }, [searchParams])

  const serviceOptions = useMemo(() => {
    const values = new Set<string>()
    if (serviceKey) {
      values.add(serviceKey)
    }
    if (entryContext.serviceKey) {
      values.add(entryContext.serviceKey)
    }
    return Array.from(values).map((item) => ({ value: item, label: item }))
  }, [entryContext.serviceKey, serviceKey])

  const latestAssistantItem = useMemo(
    () => [...history].reverse().find((item) => item.role === 'assistant'),
    [history],
  )

  const activeSuggestions = latestAssistantItem?.suggestions?.length
    ? latestAssistantItem.suggestions
    : (statusPayload?.command_suggestions || [])

  const groupedSuggestions = useMemo(() => groupSuggestions(activeSuggestions), [activeSuggestions])
  const hasEntryContext = Boolean(
    entryContext.incidentId || entryContext.recommendationId || entryContext.source !== 'manual' || entryContext.prompt,
  )

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

  useEffect(() => {
    void loadAssistantStatus()
  }, [])

  useEffect(() => {
    if (entryContext.serviceKey && entryContext.serviceKey !== serviceKey) {
      setServiceKey(entryContext.serviceKey)
    }
    if (entryContext.timeRange && entryContext.timeRange !== timeRange) {
      setTimeRange(entryContext.timeRange)
    }
    // 只在首次带上下文进入时预填提示词，避免覆盖用户正在编辑的内容。
    if (entryContext.prompt) {
      setPrompt((previous) => (previous.trim() ? previous : entryContext.prompt))
    }
  }, [entryContext.prompt, entryContext.serviceKey, entryContext.timeRange, serviceKey, setServiceKey, setTimeRange, timeRange])

  const copyText = async (value: string, successText: string) => {
    try {
      await navigator.clipboard.writeText(value)
      message.success(successText)
    } catch {
      message.error('复制失败，请手动复制')
    }
  }

  const openSourcePage = () => {
    if (entryContext.recommendationId || entryContext.source === 'recommendation') {
      const params = new URLSearchParams()
      if (entryContext.incidentId) {
        params.set('incidentId', entryContext.incidentId)
      }
      navigate(`/recommendations${params.toString() ? `?${params.toString()}` : ''}`)
      return
    }
    navigate('/incidents')
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
        service_key: serviceKey || entryContext.serviceKey || undefined,
        time_range: timeRange,
        incident_id: entryContext.incidentId || undefined,
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

      <AIProviderStatusStrip
        status={statusPayload}
        loading={statusLoading}
        onOpenSettings={() => navigate('/llm-settings')}
      />

      {hasEntryContext ? (
        <Card title="当前诊断上下文" className="ops-surface-card" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space wrap>
              <Tag color="blue">{getContextLabel(entryContext.source)}</Tag>
              {entryContext.incidentId ? <Tag>incident：{entryContext.incidentId}</Tag> : null}
              {entryContext.recommendationId ? <Tag color="purple">recommendation：{entryContext.recommendationId}</Tag> : null}
              <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || entryContext.serviceKey || '全部'}</Tag>
              <Tag>时间窗：{timeRange}</Tag>
            </Space>
            {entryContext.prompt ? (
              <Paragraph style={{ marginBottom: 0 }}>
                预设问题：{entryContext.prompt}
              </Paragraph>
            ) : null}
            <Space wrap>
              <Button size="small" onClick={() => setPrompt(entryContext.prompt || prompt)}>
                带入预设问题
              </Button>
              <Button size="small" onClick={openSourcePage}>
                返回来源页面
              </Button>
            </Space>
          </Space>
        </Card>
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="对话诊断" className="ops-surface-card">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Space wrap>
                <Tag color="blue">时间窗：{timeRange}</Tag>
                <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || '全部'}</Tag>
                <Tag color={statusPayload?.status === 'ready' ? 'green' : statusPayload?.status === 'degraded' ? 'gold' : 'red'}>
                  AI：{getStatusLabel(statusPayload?.status)}
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
