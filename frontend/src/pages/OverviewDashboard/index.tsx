import React, { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Empty, List, Row, Space, Statistic, Tag, Typography } from 'antd'
import { Line } from '@ant-design/plots'
import { dashboardApi, type DashboardOverview } from '@/api/client'

const { Paragraph, Text, Title } = Typography

export const OverviewDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState<DashboardOverview | null>(null)

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const response = (await dashboardApi.getOverview({ time_range: '1h' })) as DashboardOverview
      setData(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载总览失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const lineConfig = {
    data: (data?.traffic_trend || []).map((item) => ({
      time: item.timestamp,
      value: item.value,
    })),
    xField: 'time',
    yField: 'value',
    smooth: true,
    color: '#0f766e',
    height: 280,
  }

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>统一运维总览</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            把流量、资源、异常和任务放到同一条观察链路里，便于快速判断当前风险点。
          </Paragraph>
        </div>
        <Space>
          <Button onClick={() => void loadData()} loading={loading}>刷新数据</Button>
        </Space>
      </div>

      {error ? <Alert type="error" showIcon message="总览加载失败" description={error} style={{ marginBottom: 16 }} /> : null}

      <Row gutter={[16, 16]}>
        {(data?.cards || []).map((card) => (
          <Col xs={24} sm={12} lg={6} key={card.key}>
            <Card loading={loading} className="ops-surface-card">
              <Statistic
                title={card.label}
                value={card.value}
                suffix={card.unit}
                valueStyle={{
                  color: card.status === 'critical' ? '#b91c1c' : card.status === 'warning' ? '#c2410c' : '#0f172a',
                }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={15}>
          <Card title="请求趋势" loading={loading} className="ops-surface-card">
            {data?.traffic_trend?.length ? <Line {...lineConfig} /> : <Empty description="暂无流量数据" />}
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card title="数据源状态" loading={loading} className="ops-surface-card">
            <List
              dataSource={Object.entries(data?.data_sources || {})}
              locale={{ emptyText: '暂无数据源配置' }}
              renderItem={([name, status]) => {
                const item = status as { enabled?: boolean; configured?: boolean }
                return (
                  <List.Item>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Text strong>{name}</Text>
                      <Space>
                        <Tag color={item.enabled ? 'blue' : 'default'}>{item.enabled ? '已启用' : '未启用'}</Tag>
                        <Tag color={item.configured ? 'green' : 'gold'}>{item.configured ? '已配置' : '待配置'}</Tag>
                      </Space>
                    </Space>
                  </List.Item>
                )
              }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card title="最近异常" loading={loading} className="ops-surface-card">
            <List
              dataSource={data?.recent_incidents || []}
              locale={{ emptyText: '当前没有异常记录' }}
              renderItem={(incident) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <Space style={{ marginBottom: 8 }}>
                      <Tag color={incident.severity === 'critical' ? 'red' : incident.severity === 'warning' ? 'orange' : 'blue'}>
                        {incident.severity}
                      </Tag>
                      <Text strong>{incident.title}</Text>
                    </Space>
                    <Paragraph style={{ marginBottom: 6 }}>{incident.summary}</Paragraph>
                    <Text type="secondary">{incident.service_key}</Text>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="热点服务" loading={loading} className="ops-surface-card">
            <List
              dataSource={data?.hot_services || []}
              locale={{ emptyText: '暂无热点服务' }}
              renderItem={(item) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 6 }}>
                      <Text strong>{item.service_key}</Text>
                      <Tag color={item.score >= 85 ? 'red' : item.score >= 70 ? 'orange' : 'blue'}>{item.score.toFixed(0)}</Tag>
                    </Space>
                    <Paragraph style={{ marginBottom: 0 }}>{item.reason}</Paragraph>
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

export default OverviewDashboard
