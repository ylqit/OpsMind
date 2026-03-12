import React, { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { AutoComplete, Button, Card, Col, List, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { resourcesApi, type ResourceHotspot, type ResourceHotspotLayers, type ResourceSummary } from '@/api/client'

const { Title, Paragraph, Text } = Typography

const timeRangeOptions = [
  { label: '最近 1 小时', value: '1h' },
  { label: '最近 6 小时', value: '6h' },
  { label: '最近 24 小时', value: '24h' },
]

const allowedTimeRanges = new Set(timeRangeOptions.map((item) => item.value))

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

const normalizeTimeRange = (value: string | null | undefined) => {
  if (!value || !allowedTimeRanges.has(value)) {
    return '1h'
  }
  return value
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

const layerMeta: Array<{ key: keyof ResourceHotspotLayers; title: string; color: string }> = [
  { key: 'host', title: '主机热点', color: 'geekblue' },
  { key: 'container', title: '容器热点', color: 'orange' },
  { key: 'pod', title: 'Pod 热点', color: 'volcano' },
  { key: 'service', title: 'Service 热点', color: 'cyan' },
  { key: 'other', title: '其他热点', color: 'default' },
]

const ResourceAnalytics: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const [timeRange, setTimeRange] = useState(() => normalizeTimeRange(searchParams.get('time_range')))
  const [serviceKey, setServiceKey] = useState(() => searchParams.get('service_key') || '')
  const deferredServiceKey = useDeferredValue(serviceKey)

  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<ResourceSummary | null>(null)
  const [assets, setAssets] = useState<AssetListResponse>({ items: [], total: 0, synced: 0 })
  const [serviceKeys, setServiceKeys] = useState<string[]>([])

  const serviceOptions = useMemo(
    () => serviceKeys.map((item) => ({ value: item, label: item })),
    [serviceKeys],
  )

  const hotspotLayers = summary?.hotspot_layers || emptyHotspotLayers

  const loadData = async (override?: { timeRange?: string; serviceKey?: string }) => {
    const activeTimeRange = override?.timeRange ?? timeRange
    const activeServiceKey = override?.serviceKey ?? deferredServiceKey
    setLoading(true)
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
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [timeRange, deferredServiceKey])

  useEffect(() => {
    const nextTimeRange = normalizeTimeRange(searchParams.get('time_range'))
    const nextServiceKey = searchParams.get('service_key') || ''
    if (nextTimeRange !== timeRange) {
      setTimeRange(nextTimeRange)
    }
    if (nextServiceKey !== serviceKey) {
      setServiceKey(nextServiceKey)
    }
  }, [searchParams, timeRange, serviceKey])

  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    next.set('time_range', timeRange)
    if (serviceKey) {
      next.set('service_key', serviceKey)
    } else {
      next.delete('service_key')
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
  }, [timeRange, serviceKey, searchParams, setSearchParams])

  const hostCpu = Number(summary?.host?.cpu?.usage_percent || 0)
  const hostMemory = Number(summary?.host?.memory?.usage_percent || 0)

  const resetFilters = () => {
    setTimeRange('1h')
    setServiceKey('')
  }

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
          <Button type="link" onClick={() => void loadData({ serviceKey })}>刷新</Button>
        </Space>
      </div>

      <Space wrap style={{ marginBottom: 12 }}>
        <Tag color="blue">时间窗：{timeRange}</Tag>
        <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || '全部'}</Tag>
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card loading={loading} title="主机负载" className="ops-surface-card">
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
          <Card loading={loading} title="分层热点概览" className="ops-surface-card">
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
            <Card loading={loading} title={layerItem.title} className="ops-surface-card">
              <List
                dataSource={hotspotLayers[layerItem.key]}
                locale={{ emptyText: `当前没有${layerItem.title}` }}
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
        <Col xs={24} lg={14}>
          <Card loading={loading} title="容器摘要" className="ops-surface-card">
            <Table
              rowKey={(record) => String(record.asset_id)}
              pagination={false}
              dataSource={summary?.containers?.items || []}
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
          <Card loading={loading} title="资产目录" className="ops-surface-card">
            <List
              dataSource={assets.items}
              locale={{ emptyText: '暂无资产' }}
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
