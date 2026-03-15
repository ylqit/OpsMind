import React, { useEffect, useMemo, useState } from 'react'
import { AutoComplete, Button, Card, Col, Row, Segmented, Select, Space, Statistic, Table, Tag, Typography } from 'antd'
import { Line } from '@ant-design/plots'
import { useSearchParams } from 'react-router-dom'
import {
  metricsApi,
  resourcesApi,
  type AIUsageMetricsResponse,
  type RecommendationMetricsDimensionItem,
  type RecommendationMetricsResponse,
} from '@/api/client'
import { CardEmptyState, PageStatusBanner } from '@/components/PageState'
import { useWorkspaceFilterStore } from '@/stores/workspaceFilterStore'

const { Title, Paragraph } = Typography

interface AssetLite {
  service_key?: string
}

interface AssetListResponse {
  items: AssetLite[]
}

type RecommendationBreakdownDimension = 'provider' | 'model' | 'version'
type AIUsageBreakdownDimension = 'provider' | 'model' | 'version'
type AIUsageDimensionItem = AIUsageMetricsResponse['provider_breakdown'][number]

const windowOptions = [
  { label: '最近 7 天', value: '7d' },
  { label: '最近 14 天', value: '14d' },
  { label: '最近 30 天', value: '30d' },
]

const resolveDateRange = (windowValue: string) => {
  const now = new Date()
  const endDate = now.toISOString().slice(0, 10)
  const offsetDays = windowValue === '30d' ? 29 : windowValue === '14d' ? 13 : 6
  const start = new Date(now)
  start.setUTCDate(start.getUTCDate() - offsetDays)
  return {
    startDate: start.toISOString().slice(0, 10),
    endDate,
  }
}

const formatCost = (value: number) => `¥${value.toFixed(4)}`

const formatDuration = (value: number) => `${Math.round(value)} ms`

const mergeServiceKeys = (base: string[], incoming: string[]) => {
  const set = new Set(base)
  incoming.filter(Boolean).forEach((item) => set.add(item))
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'))
}

const mergeStringValues = (base: string[], incoming: string[]) => {
  const set = new Set(base)
  incoming.filter(Boolean).forEach((item) => set.add(item))
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'))
}

const toOptions = (values: string[]) => values.map((item) => ({ label: item, value: item }))

const getRecommendationDimensionKey = (dimension: RecommendationBreakdownDimension, row: RecommendationMetricsDimensionItem) => {
  if (dimension === 'provider') {
    return row.provider_name || 'unknown'
  }
  if (dimension === 'model') {
    return row.model || 'unknown'
  }
  return row.version || 'unknown'
}

const getRecommendationDimensionTitle = (dimension: RecommendationBreakdownDimension) => {
  if (dimension === 'provider') {
    return 'Provider'
  }
  if (dimension === 'model') {
    return '模型'
  }
  return '版本'
}

const getAIUsageDimensionKey = (dimension: AIUsageBreakdownDimension, row: AIUsageDimensionItem) => {
  if (dimension === 'provider') {
    return row.provider_name || 'unknown'
  }
  if (dimension === 'model') {
    return row.model || 'unknown'
  }
  return row.version || 'unknown'
}

const getAIUsageDimensionTitle = (dimension: AIUsageBreakdownDimension) => {
  if (dimension === 'provider') {
    return 'Provider'
  }
  if (dimension === 'model') {
    return '模型'
  }
  return '版本'
}

interface MetricsOverrideFilters {
  windowSize?: string
  serviceKey?: string
  providerName?: string
  model?: string
  version?: string
}

const QualityMetrics: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const windowSize = useWorkspaceFilterStore((state) => state.qualityWindow)
  const serviceKey = useWorkspaceFilterStore((state) => state.serviceKey)
  const providerName = useWorkspaceFilterStore((state) => state.providerName)
  const model = useWorkspaceFilterStore((state) => state.model)
  const version = useWorkspaceFilterStore((state) => state.version)
  const setWindowSize = useWorkspaceFilterStore((state) => state.setQualityWindow)
  const setServiceKey = useWorkspaceFilterStore((state) => state.setServiceKey)
  const setProviderName = useWorkspaceFilterStore((state) => state.setProviderName)
  const setModel = useWorkspaceFilterStore((state) => state.setModel)
  const setVersion = useWorkspaceFilterStore((state) => state.setVersion)
  const syncQualityFilters = useWorkspaceFilterStore((state) => state.syncQualityFilters)
  const resetQualityFilters = useWorkspaceFilterStore((state) => state.resetQualityFilters)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [recommendationMetrics, setRecommendationMetrics] = useState<RecommendationMetricsResponse | null>(null)
  const [aiUsageMetrics, setAiUsageMetrics] = useState<AIUsageMetricsResponse | null>(null)
  const [serviceKeys, setServiceKeys] = useState<string[]>([])
  const [recommendationDimension, setRecommendationDimension] = useState<RecommendationBreakdownDimension>('provider')
  const [aiUsageDimension, setAIUsageDimension] = useState<AIUsageBreakdownDimension>('provider')
  const [filtersReady, setFiltersReady] = useState(false)

  const serviceOptions = useMemo(() => toOptions(serviceKeys), [serviceKeys])

  const providerValues = useMemo(() => {
    return mergeStringValues(
      recommendationMetrics?.provider_breakdown.map((item) => item.provider_name || '') || [],
      aiUsageMetrics?.provider_breakdown.map((item) => item.provider_name || '') || [],
    )
  }, [recommendationMetrics, aiUsageMetrics])

  const modelValues = useMemo(() => {
    return mergeStringValues(
      recommendationMetrics?.model_breakdown.map((item) => item.model || '') || [],
      aiUsageMetrics?.model_breakdown.map((item) => item.model || '') || [],
    )
  }, [recommendationMetrics, aiUsageMetrics])

  const versionValues = useMemo(() => {
    return mergeStringValues(
      recommendationMetrics?.version_breakdown.map((item) => item.version || '') || [],
      aiUsageMetrics?.version_breakdown.map((item) => item.version || '') || [],
    )
  }, [recommendationMetrics, aiUsageMetrics])

  const providerOptions = useMemo(() => toOptions(providerValues), [providerValues])
  const modelOptions = useMemo(() => toOptions(modelValues), [modelValues])
  const versionOptions = useMemo(() => toOptions(versionValues), [versionValues])

  const recommendationDimensionRows = useMemo(() => {
    if (!recommendationMetrics) {
      return []
    }
    if (recommendationDimension === 'provider') {
      return recommendationMetrics.provider_breakdown
    }
    if (recommendationDimension === 'model') {
      return recommendationMetrics.model_breakdown
    }
    return recommendationMetrics.version_breakdown
  }, [recommendationMetrics, recommendationDimension])

  const aiUsageDimensionRows = useMemo(() => {
    if (!aiUsageMetrics) {
      return []
    }
    if (aiUsageDimension === 'provider') {
      return aiUsageMetrics.provider_breakdown
    }
    if (aiUsageDimension === 'model') {
      return aiUsageMetrics.model_breakdown
    }
    return aiUsageMetrics.version_breakdown
  }, [aiUsageMetrics, aiUsageDimension])

  const recommendationTrendData = useMemo(() => {
    return (
      recommendationMetrics?.trend.flatMap((item) => [
        { date: item.date, value: item.adopt_rate, type: '采纳率' },
        { date: item.date, value: item.reject_rate, type: '拒绝率' },
        { date: item.date, value: item.task_success_rate, type: '任务成功率' },
      ]) || []
    )
  }, [recommendationMetrics])

  const aiUsageTrendData = useMemo(() => {
    return (
      aiUsageMetrics?.trend.flatMap((item) => [
        { date: item.date, value: item.ai_call_total, type: '调用次数' },
        { date: item.date, value: item.ai_error_count, type: '错误次数' },
        { date: item.date, value: item.ai_timeout_count, type: '超时次数' },
        { date: item.date, value: item.guardrail_fallback_count, type: '护栏降级次数' },
      ]) || []
    )
  }, [aiUsageMetrics])

  const loadServiceKeys = async () => {
    try {
      const response = (await resourcesApi.listAssets()) as AssetListResponse
      const keys = response.items
        .map((item) => item.service_key)
        .filter((item): item is string => typeof item === 'string' && item.length > 0)
      setServiceKeys((prev) => mergeServiceKeys(prev, keys))
    } catch {
      // 资产列表不是主链路依赖，不阻塞质量看板加载。
    }
  }

  const loadMetrics = async (override?: MetricsOverrideFilters) => {
    const activeWindow = override?.windowSize ?? windowSize
    const activeService = override?.serviceKey ?? serviceKey
    const activeProvider = override?.providerName ?? providerName
    const activeModel = override?.model ?? model
    const activeVersion = override?.version ?? version
    const { startDate, endDate } = resolveDateRange(activeWindow)

    setLoading(true)
    setError('')
    try {
      // 两个指标接口共享同一批筛选条件，保证不同卡片口径一致。
      const [recommendationResponse, aiUsageResponse] = await Promise.all([
        metricsApi.getRecommendation({
          start_date: startDate,
          end_date: endDate,
          service_key: activeService || undefined,
          provider_name: activeProvider || undefined,
          model: activeModel || undefined,
          version: activeVersion || undefined,
        }) as Promise<RecommendationMetricsResponse>,
        metricsApi.getAiUsage({
          start_date: startDate,
          end_date: endDate,
          service_key: activeService || undefined,
          provider_name: activeProvider || undefined,
          model: activeModel || undefined,
          version: activeVersion || undefined,
          sync_daily: true,
        }) as Promise<AIUsageMetricsResponse>,
      ])

      setRecommendationMetrics(recommendationResponse)
      setAiUsageMetrics(aiUsageResponse)
      setServiceKeys((prev) => mergeServiceKeys(prev, recommendationResponse.service_breakdown.map((item) => item.service_key)))
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '质量看板数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadServiceKeys()
  }, [])

  useEffect(() => {
    if (!filtersReady) {
      return
    }
    void loadMetrics()
  }, [filtersReady, windowSize, serviceKey, providerName, model, version])

  useEffect(() => {
    syncQualityFilters({
      window: searchParams.get('window'),
      serviceKey: searchParams.get('service_key'),
      providerName: searchParams.get('provider_name'),
      model: searchParams.get('model'),
      version: searchParams.get('version'),
    })
    setFiltersReady(true)
  }, [searchParams, syncQualityFilters])

  useEffect(() => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set('window', windowSize)
      if (serviceKey) {
        next.set('service_key', serviceKey)
      } else {
        next.delete('service_key')
      }
      if (providerName) {
        next.set('provider_name', providerName)
      } else {
        next.delete('provider_name')
      }
      if (model) {
        next.set('model', model)
      } else {
        next.delete('model')
      }
      if (version) {
        next.set('version', version)
      } else {
        next.delete('version')
      }
      if (next.toString() === previous.toString()) {
        return previous
      }
      return next
    }, { replace: true, preventScrollReset: true })
  }, [windowSize, serviceKey, providerName, model, version, setSearchParams])

  const resetFilters = () => {
    resetQualityFilters()
  }

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>质量看板</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            统一观察建议采纳、任务执行稳定性与 AI 调用成本，支持按服务、Provider、模型与版本做下钻回看。
          </Paragraph>
        </div>
        <Space wrap>
          <Select value={windowSize} options={windowOptions} style={{ width: 132 }} onChange={setWindowSize} />
          <AutoComplete
            value={serviceKey}
            options={serviceOptions}
            onChange={setServiceKey}
            placeholder="全部服务"
            style={{ width: 220 }}
            filterOption={(input, option) => String(option?.value || '').toLowerCase().includes(input.toLowerCase())}
          />
          <Select
            allowClear
            value={providerName || undefined}
            options={providerOptions}
            style={{ width: 180 }}
            placeholder="全部 Provider"
            onChange={(value) => setProviderName(value || '')}
          />
          <Select
            allowClear
            value={model || undefined}
            options={modelOptions}
            style={{ width: 220 }}
            placeholder="全部模型"
            onChange={(value) => setModel(value || '')}
          />
          <Select
            allowClear
            value={version || undefined}
            options={versionOptions}
            style={{ width: 160 }}
            placeholder="全部版本"
            onChange={(value) => setVersion(value || '')}
          />
          <Button onClick={resetFilters}>重置</Button>
          <Button type="link" onClick={() => void loadMetrics()}>刷新</Button>
        </Space>
      </div>

      {error ? (
        <PageStatusBanner
          type="error"
          title="质量看板加载失败"
          description={error}
          actionText="重新加载"
          onAction={() => void loadMetrics()}
        />
      ) : null}

      <Space wrap style={{ marginBottom: 4 }}>
        <Tag color="blue">时间窗：{windowSize}</Tag>
        <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || '全部'}</Tag>
        <Tag color={providerName ? 'cyan' : 'default'}>Provider：{providerName || '全部'}</Tag>
        <Tag color={model ? 'purple' : 'default'}>模型：{model || '全部'}</Tag>
        <Tag color={version ? 'gold' : 'default'}>版本：{version || '全部'}</Tag>
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="建议采纳率" value={recommendationMetrics?.summary.adopt_rate || 0} precision={2} suffix="%" />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="任务成功率" value={recommendationMetrics?.summary.task_success_rate || 0} precision={2} suffix="%" />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="平均任务耗时" value={recommendationMetrics?.summary.avg_task_duration_ms || 0} precision={0} suffix="ms" />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="反馈总数" value={recommendationMetrics?.summary.feedback_total || 0} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="AI 调用次数" value={aiUsageMetrics?.summary.ai_call_total || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="AI 错误率" value={aiUsageMetrics?.summary.ai_error_rate || 0} precision={2} suffix="%" />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="超时次数" value={aiUsageMetrics?.summary.ai_timeout_count || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="护栏降级次数" value={aiUsageMetrics?.summary.guardrail_fallback_count || 0} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="Schema 校验失败" value={aiUsageMetrics?.summary.guardrail_schema_error_count || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="护栏重试次数" value={aiUsageMetrics?.summary.guardrail_retried_count || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="平均调用延迟" value={aiUsageMetrics?.summary.ai_avg_latency_ms || 0} precision={0} suffix="ms" />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading} className="ops-surface-card">
            <Statistic title="总成本估算" value={aiUsageMetrics?.summary.ai_total_cost || 0} precision={4} prefix="¥" />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="建议与任务质量趋势" loading={loading} className="ops-surface-card">
            {recommendationTrendData.length ? (
              <Line
                data={recommendationTrendData}
                xField="date"
                yField="value"
                seriesField="type"
                color={['#16a34a', '#ef4444', '#2563eb']}
                height={300}
                smooth
              />
            ) : (
              <CardEmptyState title="暂无 recommendation 指标数据" description="当前筛选条件下还没有建议质量样本。" />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="AI 调用趋势" loading={loading} className="ops-surface-card">
            {aiUsageTrendData.length ? (
              <Line
                data={aiUsageTrendData}
                xField="date"
                yField="value"
                seriesField="type"
                color={['#0ea5e9', '#f97316', '#dc2626', '#7c3aed']}
                height={300}
                smooth
              />
            ) : (
              <CardEmptyState title="暂无 AI 调用数据" description="当前筛选条件下还没有调用趋势样本。" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="服务质量下钻" loading={loading} className="ops-surface-card">
            <Table
              size="small"
              rowKey="service_key"
              pagination={false}
              dataSource={recommendationMetrics?.service_breakdown || []}
              locale={{ emptyText: <CardEmptyState title="暂无服务质量数据" /> }}
              columns={[
                {
                  title: '服务',
                  dataIndex: 'service_key',
                  render: (value: string) => <Tag color="geekblue">{value}</Tag>,
                },
                {
                  title: '反馈总数',
                  dataIndex: 'feedback_total',
                },
                {
                  title: '采纳率',
                  dataIndex: 'adopt_rate',
                  render: (value: number) => `${value.toFixed(2)}%`,
                },
                {
                  title: '任务成功率',
                  dataIndex: 'task_success_rate',
                  render: (value: number) => `${value.toFixed(2)}%`,
                },
                {
                  title: '平均任务耗时',
                  dataIndex: 'avg_task_duration_ms',
                  render: (value: number) => formatDuration(value),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            title="建议质量分维下钻"
            loading={loading}
            className="ops-surface-card"
            extra={(
              <Segmented<RecommendationBreakdownDimension>
                value={recommendationDimension}
                options={[
                  { label: 'Provider', value: 'provider' },
                  { label: '模型', value: 'model' },
                  { label: '版本', value: 'version' },
                ]}
                onChange={(value) => setRecommendationDimension(value)}
              />
            )}
          >
            <Table
              size="small"
              rowKey={(row) => getRecommendationDimensionKey(recommendationDimension, row)}
              pagination={false}
              dataSource={recommendationDimensionRows}
              locale={{ emptyText: <CardEmptyState title="暂无建议分维数据" /> }}
              columns={[
                {
                  title: getRecommendationDimensionTitle(recommendationDimension),
                  render: (_: unknown, row: RecommendationMetricsDimensionItem) => (
                    <Tag color="blue">{getRecommendationDimensionKey(recommendationDimension, row)}</Tag>
                  ),
                },
                {
                  title: '反馈总数',
                  dataIndex: 'feedback_total',
                },
                {
                  title: '采纳率',
                  dataIndex: 'adopt_rate',
                  render: (value: number) => `${value.toFixed(2)}%`,
                },
                {
                  title: '任务成功率',
                  dataIndex: 'task_success_rate',
                  render: (value: number) => `${value.toFixed(2)}%`,
                },
                {
                  title: '任务审批率',
                  dataIndex: 'task_approval_rate',
                  render: (value: number) => `${value.toFixed(2)}%`,
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24}>
          <Card
            title="AI 调用分维下钻"
            loading={loading}
            className="ops-surface-card"
            extra={(
              <Segmented<AIUsageBreakdownDimension>
                value={aiUsageDimension}
                options={[
                  { label: 'Provider', value: 'provider' },
                  { label: '模型', value: 'model' },
                  { label: '版本', value: 'version' },
                ]}
                onChange={(value) => setAIUsageDimension(value)}
              />
            )}
          >
            <Table
              size="small"
              rowKey={(row) => `${aiUsageDimension}-${getAIUsageDimensionKey(aiUsageDimension, row)}`}
              pagination={false}
              dataSource={aiUsageDimensionRows}
              locale={{ emptyText: <CardEmptyState title="暂无 AI 分维数据" /> }}
              columns={[
                {
                  title: getAIUsageDimensionTitle(aiUsageDimension),
                  render: (_: unknown, row: AIUsageDimensionItem) => (
                    <Tag color="cyan">{getAIUsageDimensionKey(aiUsageDimension, row)}</Tag>
                  ),
                },
                {
                  title: '调用次数',
                  dataIndex: 'ai_call_total',
                },
                {
                  title: '错误率',
                  dataIndex: 'ai_error_rate',
                  render: (value: number) => `${value.toFixed(2)}%`,
                },
                {
                  title: '超时次数',
                  dataIndex: 'ai_timeout_count',
                },
                {
                  title: '护栏降级',
                  dataIndex: 'guardrail_fallback_count',
                },
                {
                  title: '总 Token',
                  dataIndex: 'ai_total_tokens',
                },
                {
                  title: '成本估算',
                  dataIndex: 'ai_total_cost',
                  render: (value: number) => formatCost(value),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default QualityMetrics
