import React, { useEffect, useState } from 'react'
import { Button, Card, Col, Empty, Input, Row, Select, Space, Statistic, Table, Typography } from 'antd'
import { Pie, Column } from '@ant-design/plots'
import { trafficApi, type TrafficSummary } from '@/api/client'

const { Title, Paragraph } = Typography

const timeRangeOptions = [
  { label: '最近 1 小时', value: '1h' },
  { label: '最近 6 小时', value: '6h' },
  { label: '最近 24 小时', value: '24h' },
]

export const TrafficAnalytics: React.FC = () => {
  const [timeRange, setTimeRange] = useState('1h')
  const [serviceKey, setServiceKey] = useState('')
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<TrafficSummary | null>(null)

  const loadSummary = async () => {
    setLoading(true)
    try {
      const response = (await trafficApi.getSummary({
        time_range: timeRange,
        service_key: serviceKey || undefined,
      })) as TrafficSummary
      setSummary(response)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSummary()
  }, [timeRange])

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>流量分析</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            观察请求量、状态码、热点路径和来源分布，快速定位入口异常与流量结构变化。
          </Paragraph>
        </div>
        <Space wrap>
          <Select value={timeRange} onChange={setTimeRange} options={timeRangeOptions} style={{ width: 140 }} />
          <Input value={serviceKey} onChange={(event) => setServiceKey(event.target.value)} placeholder="按 service_key 过滤" style={{ width: 220 }} />
          <Button type="link" onClick={() => void loadSummary()}>刷新</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={8}>
          <Card loading={loading} className="ops-surface-card"><Statistic title="总请求数" value={summary?.total_requests || 0} /></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card loading={loading} className="ops-surface-card"><Statistic title="页面浏览量" value={summary?.page_views || 0} /></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card loading={loading} className="ops-surface-card"><Statistic title="错误率" value={summary?.error_rate || 0} precision={2} suffix="%" /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="状态码分布" loading={loading} className="ops-surface-card">
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
        <Col xs={24} lg={12}>
          <Card title="区域分布" loading={loading} className="ops-surface-card">
            {summary?.geo_distribution?.length ? (
              <Column data={summary.geo_distribution} xField="name" yField="value" color="#2563eb" height={280} />
            ) : <Empty description="暂无地域数据" />}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="热点路径" loading={loading} className="ops-surface-card">
            <Table
              rowKey="path"
              pagination={false}
              dataSource={summary?.top_paths || []}
              columns={[
                { title: '路径', dataIndex: 'path' },
                { title: '请求数', dataIndex: 'count', width: 120 },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="热点来源 IP" loading={loading} className="ops-surface-card">
            <Table
              rowKey="ip"
              pagination={false}
              dataSource={summary?.top_ips || []}
              columns={[
                { title: 'IP', dataIndex: 'ip' },
                { title: '请求数', dataIndex: 'count', width: 120 },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default TrafficAnalytics
