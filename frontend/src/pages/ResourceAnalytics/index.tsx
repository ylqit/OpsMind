import React, { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { AutoComplete, Badge, Button, Card, Col, List, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import {
  resourcesApi,
  type ResourceHotspot,
  type ResourceHotspotLayers,
  type ResourceRiskItem,
  type ResourceRiskSummary,
  type ResourceSummary,
} from '@/api/client'
import { CardEmptyState, PageStatusBanner } from '@/components/PageState'
import { useWorkspaceFilterStore } from '@/stores/workspaceFilterStore'

const { Title, Paragraph, Text } = Typography

const timeRangeOptions = [
  { label: '最近 1 小时', value: '1h' },
  { label: '最近 6 小时', value: '6h' },
  { label: '最近 24 小时', value: '24h' },
]

const timeRangeLabelMap: Record<string, string> = Object.fromEntries(
  timeRangeOptions.map((item) => [item.value, item.label]),
) as Record<string, string>

interface AssetItem {
  asset_id?: string
  asset_type?: string
  name?: string
  service_key?: string
}

interface AssetListResponse {
  items: AssetItem[]
  total: number
  synced: number
}

const emptyHotspotLayers: ResourceHotspotLayers = {
  host: [],
  container: [],
  pod: [],
  service: [],
  other: [],
}

const emptyRiskSummary: ResourceRiskSummary = {
  total: 0,
  levels: {
    critical: 0,
    high: 0,
    medium: 0,
  },
  oom: {
    total: 0,
    critical: 0,
    high: 0,
    medium: 0,
  },
  restart: {
    total: 0,
    critical: 0,
    high: 0,
    medium: 0,
  },
}

const mergeServiceKeys = (base: string[], incoming: string[]) => {
  const set = new Set(base)
  incoming.filter(Boolean).forEach((item) => set.add(item))
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'))
}

const formatHotspotValue = (item: ResourceHotspot) => {
  if (item.value === null || item.value === undefined || item.value === '') {
    return '-'
  }
  return `${item.value}${item.unit ? ` ${item.unit}` : ''}`
}

const formatRiskValue = (item: ResourceRiskItem) => {
  if (item.value === null || item.value === undefined || item.value === '') {
    return '-'
  }
  return `${item.value}${item.unit ? ` ${item.unit}` : ''}`
}

const riskTypeLabel = (riskType: string) => {
  if (riskType === 'oom') {
    return 'OOM'
  }
  return '重启'
}

const riskLevelLabel = (level: string) => {
  if (level === 'critical') {
    return '严重'
  }
  if (level === 'high') {
    return '高'
  }
  return '中'
}

const riskLevelColor = (level: string) => {
  if (level === 'critical') {
    return 'red'
  }
  if (level === 'high') {
    return 'orange'
  }
  return 'gold'
}

const layerMeta: Array<{ key: keyof ResourceHotspotLayers; title: string; color: string }> = [
  { key: 'host', title: '主机热点', color: 'geekblue' },
  { key: 'container', title: '容器热点', color: 'orange' },
  { key: 'pod', title: 'Pod 热点', color: 'volcano' },
  { key: 'service', title: 'Service 热点', color: 'cyan' },
  { key: 'other', title: '其他热点', color: 'default' },
]

const ResourceAnalytics: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const timeRange = useWorkspaceFilterStore((state) => state.timeRange)
  const serviceKey = useWorkspaceFilterStore((state) => state.serviceKey)
  const setTimeRange = useWorkspaceFilterStore((state) => state.setTimeRange)
  const setServiceKey = useWorkspaceFilterStore((state) => state.setServiceKey)
  const syncOpsFilters = useWorkspaceFilterStore((state) => state.syncOpsFilters)
  const resetOpsFilters = useWorkspaceFilterStore((state) => state.resetOpsFilters)
  const deferredServiceKey = useDeferredValue(serviceKey)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState<ResourceSummary | null>(null)
  const [assets, setAssets] = useState<AssetListResponse>({ items: [], total: 0, synced: 0 })
  const [serviceKeys, setServiceKeys] = useState<string[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [filtersReady, setFiltersReady] = useState(false)
  const bootLoading = loading && !summary

  const serviceOptions = useMemo(
    () => serviceKeys.map((item) => ({ value: item, label: item })),
    [serviceKeys],
  )

  const hotspotLayers = summary?.hotspot_layers || emptyHotspotLayers
  const riskSummary = summary?.risk_summary || emptyRiskSummary
  const riskItems = summary?.risk_items || []

  const loadData = async (override?: { timeRange?: string; serviceKey?: string }) => {
    const activeTimeRange = override?.timeRange ?? timeRange
    const activeServiceKey = override?.serviceKey ?? deferredServiceKey
    const hasSnapshot = Boolean(summary)
    if (hasSnapshot) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError('')
    try {
      const [resourceResponse, assetResponse] = await Promise.all([
        resourcesApi.getSummary({ time_range: activeTimeRange, service_key: activeServiceKey || undefined }) as Promise<ResourceSummary>,
        resourcesApi.listAssets({ service_key: activeServiceKey || undefined }) as Promise<AssetListResponse>,
      ])
      setSummary(resourceResponse)
      setAssets(assetResponse)
      const keys = assetResponse.items
        .map((item) => item.service_key)
        .filter((item): item is string => typeof item === 'string' && item.length > 0)
      setServiceKeys((prev) => mergeServiceKeys(prev, keys))
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '资源分析加载失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    if (!filtersReady) {
      return
    }
    void loadData()
  }, [filtersReady, timeRange, deferredServiceKey])

  useEffect(() => {
    const nextTimeRange = searchParams.get('time_range')
    const nextServiceKey = searchParams.get('service_key')
    syncOpsFilters({ timeRange: nextTimeRange, serviceKey: nextServiceKey })
    setFiltersReady(true)
  }, [searchParams, syncOpsFilters])

  useEffect(() => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set('time_range', timeRange)
      if (serviceKey) {
        next.set('service_key', serviceKey)
      } else {
        next.delete('service_key')
      }
      if (next.toString() === previous.toString()) {
        return previous
      }
      return next
    }, { replace: true, preventScrollReset: true })
  }, [timeRange, serviceKey, setSearchParams])

  const hostCpu = Number(summary?.host?.cpu?.usage_percent || 0)
  const hostMemory = Number(summary?.host?.memory?.usage_percent || 0)

  const resetFilters = () => resetOpsFilters()

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>资源分析</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            汇总主机、容器和 Prometheus 指标，按时间窗和服务维度定位重启、OOM 与资源热点。
          </Paragraph>
        </div>
        <Space wrap>
          <Select value={timeRange} onChange={setTimeRange} options={timeRangeOptions} style={{ width: 140 }} />
          <AutoComplete
            value={serviceKey}
            options={serviceOptions}
            onChange={setServiceKey}
            placeholder="输入或选择 service_key"
            style={{ width: 240 }}
            filterOption={(inputValue, option) => String(option?.value || '').toLowerCase().includes(inputValue.toLowerCase())}
          />
          <Button onClick={resetFilters}>重置</Button>
          <Button type="link" loading={refreshing} onClick={() => void loadData({ serviceKey })}>刷新</Button>
        </Space>
      </div>

      {error ? (
        <PageStatusBanner
          type="error"
          title="资源分析加载失败"
          description={error}
          actionText="重新加载"
          onAction={() => void loadData()}
        />
      ) : null}

      <Space wrap style={{ marginBottom: 12 }}>
        <Tag color="blue">时间窗：{timeRangeLabelMap[timeRange] || timeRange}</Tag>
        <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || '全部'}</Tag>
        <Badge status={refreshing ? 'processing' : 'default'} text={refreshing ? '正在刷新数据' : '数据稳定'} />
      </Space>

      <Row gutter={[16, 16]} style={{ marginBottom: 8 }}>
        <Col xs={24} md={12}>
          <Card loading={bootLoading} title="OOM/重启风险概览" className="ops-surface-card">
            <List
              dataSource={[
                { label: '风险总数', value: `${riskSummary.total}` },
                { label: 'OOM 风险', value: `${riskSummary.oom.total} (严重 ${riskSummary.oom.critical})` },
                {
                  label: '重启风险',
                  value: `${riskSummary.restart.total} (严重 ${riskSummary.restart.critical} / 高 ${riskSummary.restart.high} / 中 ${riskSummary.restart.medium})`,
                },
              ]}
              renderItem={(item) => (
                <List.Item>
                  <Text>{item.label}</Text>
                  <Text strong>{item.value}</Text>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card loading={bootLoading} title="风险等级分布" className="ops-surface-card">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Tag color="red">严重</Tag>
                <Text strong>{riskSummary.levels.critical}</Text>
              </Space>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Tag color="orange">高</Tag>
                <Text strong>{riskSummary.levels.high}</Text>
              </Space>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Tag color="gold">中</Tag>
                <Text strong>{riskSummary.levels.medium}</Text>
              </Space>
              {riskSummary.total === 0 ? <Text type="secondary">当前时间窗未发现 OOM 或重启风险</Text> : null}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card loading={bootLoading} title="主机负载" className="ops-surface-card">
            <List
              dataSource={[
                { label: 'CPU 使用率', value: `${hostCpu.toFixed(1)}%` },
                { label: '内存使用率', value: `${hostMemory.toFixed(1)}%` },
                { label: '自动发现资产', value: `${assets.total}` },
              ]}
              renderItem={(item) => (
                <List.Item>
                  <Text>{item.label}</Text>
                  <Text strong>{item.value}</Text>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card loading={bootLoading} title="分层热点概览" className="ops-surface-card">
            <List
              dataSource={layerMeta}
              renderItem={(item) => (
                <List.Item>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Tag color={item.color}>{item.title}</Tag>
                    <Text strong>{hotspotLayers[item.key].length} 项</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        {layerMeta.map((layerItem) => (
          <Col xs={24} lg={12} key={layerItem.key}>
            <Card loading={bootLoading} title={layerItem.title} className="ops-surface-card">
              <List
                dataSource={hotspotLayers[layerItem.key]}
                locale={{ emptyText: <CardEmptyState title={`当前没有${layerItem.title}`} /> }}
                renderItem={(item) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space style={{ marginBottom: 6, width: '100%', justifyContent: 'space-between' }}>
                        <Text strong>{item.name}</Text>
                        <Tag color={item.score >= 90 ? 'red' : item.score >= 70 ? 'orange' : 'blue'}>{item.score.toFixed(0)}</Tag>
                      </Space>
                      <Paragraph style={{ marginBottom: 6 }}>{item.reason}</Paragraph>
                      <Space wrap>
                        <Tag>{item.metric}</Tag>
                        <Tag color="geekblue">{formatHotspotValue(item)}</Tag>
                        {item.service_key ? <Tag color="cyan">{item.service_key}</Tag> : null}
                        {item.namespace ? <Tag>{item.namespace}</Tag> : null}
                      </Space>
                    </div>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24}>
          <Card loading={bootLoading} title="OOM/重启风险清单" className="ops-surface-card">
            <Table
              rowKey={(record) => String(record.risk_id)}
              pagination={false}
              dataSource={riskItems}
              columns={[
                {
                  title: '类型',
                  dataIndex: 'risk_type',
                  width: 90,
                  render: (value: string) => <Tag color={value === 'oom' ? 'red' : 'orange'}>{riskTypeLabel(value)}</Tag>,
                },
                {
                  title: '等级',
                  dataIndex: 'level',
                  width: 90,
                  render: (value: string) => <Tag color={riskLevelColor(value)}>{riskLevelLabel(value)}</Tag>,
                },
                { title: '对象', dataIndex: 'target', width: 180 },
                { title: '层级', dataIndex: 'layer', width: 100 },
                {
                  title: '指标值',
                  width: 120,
                  render: (_: unknown, record: ResourceRiskItem) => formatRiskValue(record),
                },
                {
                  title: '证据',
                  dataIndex: 'evidence',
                  ellipsis: true,
                },
                {
                  title: '服务键',
                  dataIndex: 'service_key',
                  width: 220,
                  ellipsis: true,
                },
              ]}
              locale={{ emptyText: <CardEmptyState title="当前时间窗暂无 OOM/重启风险" /> }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={14}>
          <Card loading={bootLoading} title="容器摘要" className="ops-surface-card">
            <Table
              rowKey={(record) => String(record.asset_id)}
              pagination={false}
              dataSource={summary?.containers?.items || []}
              locale={{ emptyText: <CardEmptyState title="暂无容器摘要" /> }}
              columns={[
                { title: '容器', dataIndex: 'name' },
                { title: '服务键', dataIndex: 'service_key' },
                { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'running' ? 'green' : 'gold'}>{value}</Tag> },
                { title: '重启次数', dataIndex: 'restarts', width: 120 },
                { title: 'OOM', dataIndex: 'oom_killed', width: 100, render: (value: boolean) => <Tag color={value ? 'red' : 'blue'}>{value ? '是' : '否'}</Tag> },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card loading={bootLoading} title="资产目录" className="ops-surface-card">
            <List
              dataSource={assets.items}
              locale={{ emptyText: <CardEmptyState title="暂无资产" /> }}
              renderItem={(item) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <Text strong>{String(item.name || '-')}</Text>
                      <Tag>{String(item.asset_type || '-')}</Tag>
                    </div>
                    <Text type="secondary">{String(item.service_key || '-')}</Text>
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

export default ResourceAnalytics
