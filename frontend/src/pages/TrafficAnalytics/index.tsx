import React, { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { AutoComplete, Badge, Button, Card, Col, Empty, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd'
import { Column, Line, Pie } from '@ant-design/plots'
import { useSearchParams } from 'react-router-dom'
import { resourcesApi, trafficApi, type TrafficErrorSample, type TrafficSummary } from '@/api/client'
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

interface AssetLite {
  service_key?: string
}

interface AssetListResponse {
  items: AssetLite[]
}

const mergeServiceKeys = (base: string[], incoming: string[]) => {
  const set = new Set(base)
  incoming.filter(Boolean).forEach((item) => set.add(item))
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'))
}

const extractServiceKeysFromRecords = (records: Array<Record<string, unknown>> | undefined) => {
  if (!records?.length) {
    return []
  }
  return records
    .map((item) => item.service_key)
    .filter((item): item is string => typeof item === 'string' && item.length > 0)
}

const formatSampleTime = (value: string) => {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

const formatLatency = (value: number) => `${Math.round(value * 1000)} ms`

const TrafficAnalytics: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const timeRange = useWorkspaceFilterStore((state) => state.timeRange)
  const serviceKey = useWorkspaceFilterStore((state) => state.serviceKey)
  const setTimeRange = useWorkspaceFilterStore((state) => state.setTimeRange)
  const setServiceKey = useWorkspaceFilterStore((state) => state.setServiceKey)
  const syncOpsFilters = useWorkspaceFilterStore((state) => state.syncOpsFilters)
  const resetOpsFilters = useWorkspaceFilterStore((state) => state.resetOpsFilters)
  const deferredServiceKey = useDeferredValue(serviceKey)

  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<TrafficSummary | null>(null)
  const [serviceKeys, setServiceKeys] = useState<string[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [filtersReady, setFiltersReady] = useState(false)
  const bootLoading = loading && !summary

  const serviceOptions = useMemo(
    () => serviceKeys.map((item) => ({ value: item, label: item })),
    [serviceKeys],
  )

  const loadServiceKeys = async () => {
    try {
      const response = (await resourcesApi.listAssets()) as AssetListResponse
      const keys = response.items
        .map((item) => item.service_key)
        .filter((item): item is string => typeof item === 'string' && item.length > 0)
      setServiceKeys((prev) => mergeServiceKeys(prev, keys))
    } catch {
      // 资产接口异常时不阻塞流量分析主流程。
    }
  }

  const loadSummary = async (override?: { timeRange?: string; serviceKey?: string }) => {
    const activeTimeRange = override?.timeRange ?? timeRange
    const activeServiceKey = override?.serviceKey ?? deferredServiceKey
    const hasSnapshot = Boolean(summary)
    if (hasSnapshot) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    try {
      const response = (await trafficApi.getSummary({
        time_range: activeTimeRange,
        service_key: activeServiceKey || undefined,
      })) as TrafficSummary
      setSummary(response)
      const keysFromRecords = extractServiceKeysFromRecords(response.records_sample)
      setServiceKeys((prev) => mergeServiceKeys(prev, keysFromRecords))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void loadServiceKeys()
  }, [])

  useEffect(() => {
    if (!filtersReady) {
      return
    }
    void loadSummary()
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

  // 把请求数和错误数压平成统一序列，图表层可以直接按类型分组绘制。
  const trendData = useMemo(
    () =>
      summary?.trend.flatMap((point) => [
        { timestamp: point.timestamp, value: point.requests, type: '请求数' },
        { timestamp: point.timestamp, value: point.errors, type: '错误数' },
      ]) ?? [],
    [summary],
  )

  const resetFilters = () => resetOpsFilters()

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>流量分析</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            观察请求趋势、热点路径、异常来源 IP 和错误样本，快速判断入口异常集中在哪里、影响有多大。
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
          <Button type="link" loading={refreshing} onClick={() => void loadSummary({ serviceKey })}>刷新</Button>
        </Space>
      </div>

      <Space wrap style={{ marginBottom: 12 }}>
        <Tag color="blue">时间窗：{timeRangeLabelMap[timeRange] || timeRange}</Tag>
        <Tag color={serviceKey ? 'geekblue' : 'default'}>服务：{serviceKey || '全部'}</Tag>
        <Badge status={refreshing ? 'processing' : 'default'} text={refreshing ? '正在刷新数据' : '数据稳定'} />
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={6}>
          <Card loading={bootLoading} className="ops-surface-card"><Statistic title="总请求数" value={summary?.total_requests || 0} /></Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card loading={bootLoading} className="ops-surface-card"><Statistic title="页面浏览量" value={summary?.page_views || 0} /></Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card loading={bootLoading} className="ops-surface-card"><Statistic title="错误率" value={summary?.error_rate || 0} precision={2} suffix="%" /></Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card loading={bootLoading} className="ops-surface-card"><Statistic title="平均延迟" value={(summary?.avg_latency || 0) * 1000} precision={0} suffix="ms" /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={14}>
          <Card title="请求趋势" loading={bootLoading} className="ops-surface-card">
            {trendData.length ? (
              <Line
                data={trendData}
                xField="timestamp"
                yField="value"
                seriesField="type"
                height={280}
                color={["#2563eb", "#ef4444"]}
                point={{ size: 3 }}
                smooth
              />
            ) : <Empty description="暂无趋势数据" />}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="状态码分布" loading={bootLoading} className="ops-surface-card">
            {summary?.status_distribution?.length ? (
              <Pie
                data={summary.status_distribution.map((item) => ({ type: item.status, value: item.count }))}
                angleField="value"
                colorField="type"
                height={280}
              />
            ) : <Empty description="暂无状态码数据" />}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="热点路径排行" loading={bootLoading} className="ops-surface-card">
            <Table
              rowKey="path"
              pagination={false}
              dataSource={summary?.hot_paths || []}
              locale={{ emptyText: <Empty description="暂无热点路径数据" /> }}
              columns={[
                {
                  title: '路径',
                  dataIndex: 'path',
                  render: (value: string) => <Text code>{value}</Text>,
                },
                { title: '请求数', dataIndex: 'count', width: 96 },
                { title: '错误数', dataIndex: 'error_count', width: 96 },
                { title: '错误率', dataIndex: 'error_rate', width: 110, render: (value: number) => `${value}%` },
                { title: '平均耗时', dataIndex: 'avg_latency', width: 120, render: (value: number) => formatLatency(value) },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="异常来源 IP" loading={bootLoading} className="ops-surface-card">
            <Table
              rowKey="ip"
              pagination={false}
              dataSource={summary?.hot_ips || []}
              locale={{ emptyText: <Empty description="暂无异常来源 IP" /> }}
              columns={[
                { title: 'IP', dataIndex: 'ip', width: 148 },
                { title: '请求数', dataIndex: 'count', width: 84 },
                { title: '错误数', dataIndex: 'error_count', width: 84 },
                { title: '错误率', dataIndex: 'error_rate', width: 96, render: (value: number) => `${value}%` },
                { title: '样本路径', dataIndex: 'sample_path', render: (value: string) => <Text code>{value}</Text> },
                { title: '地域', dataIndex: 'geo_label', width: 140 },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="热门路径分布" loading={bootLoading} className="ops-surface-card">
            {summary?.top_paths?.length ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {summary.top_paths.map((item) => (
                  <Tag key={item.path} color="blue" style={{ padding: '8px 12px', borderRadius: 999 }}>
                    {item.path} · {item.count}
                  </Tag>
                ))}
              </div>
            ) : <Empty description="暂无路径分布" />}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="终端分布" loading={bootLoading} className="ops-surface-card">
            {summary?.ua_distribution?.length ? (
              <Column data={summary.ua_distribution} xField="name" yField="count" color="#0f766e" height={240} />
            ) : <Empty description="暂无终端分布" />}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={24}>
          <Card title="错误请求样本" loading={bootLoading} className="ops-surface-card">
            <Table
              rowKey={(record: TrafficErrorSample, index?: number) => `${record.timestamp}-${record.path}-${index || 0}`}
              pagination={false}
              dataSource={summary?.error_samples || []}
              locale={{ emptyText: <Empty description="当前时间窗没有高风险请求样本" /> }}
              columns={[
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 90,
                  render: (value: number) => <Tag color={value >= 500 ? 'red' : value >= 400 ? 'orange' : 'blue'}>{value}</Tag>,
                },
                { title: '方法', dataIndex: 'method', width: 90 },
                {
                  title: '路径',
                  dataIndex: 'path',
                  render: (value: string) => <Text code>{value}</Text>,
                },
                {
                  title: '耗时',
                  dataIndex: 'latency_ms',
                  width: 110,
                  render: (value: number) => `${value} ms`,
                },
                { title: '来源 IP', dataIndex: 'client_ip', width: 150 },
                { title: '地域', dataIndex: 'geo_label', width: 180 },
                {
                  title: '终端',
                  key: 'ua',
                  render: (_, record: TrafficErrorSample) => `${record.browser} / ${record.os} / ${record.device}`,
                },
                {
                  title: '时间',
                  dataIndex: 'timestamp',
                  width: 180,
                  render: (value: string) => formatSampleTime(value),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default TrafficAnalytics
