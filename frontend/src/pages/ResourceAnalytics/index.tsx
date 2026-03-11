import React, { useEffect, useState } from 'react'
import { Card, Col, List, Row, Table, Tag, Typography } from 'antd'
import { resourcesApi, type ResourceSummary } from '@/api/client'

const { Title, Paragraph, Text } = Typography

interface AssetListResponse {
  items: Array<Record<string, unknown>>
  total: number
  synced: number
}

export const ResourceAnalytics: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<ResourceSummary | null>(null)
  const [assets, setAssets] = useState<AssetListResponse>({ items: [], total: 0, synced: 0 })

  const loadData = async () => {
    setLoading(true)
    try {
      const [resourceResponse, assetResponse] = await Promise.all([
        resourcesApi.getSummary({ time_range: '1h' }) as Promise<ResourceSummary>,
        resourcesApi.listAssets() as Promise<AssetListResponse>,
      ])
      setSummary(resourceResponse)
      setAssets(assetResponse)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const hostCpu = Number(summary?.host?.cpu?.usage_percent || 0)
  const hostMemory = Number(summary?.host?.memory?.usage_percent || 0)

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>资源分析</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            汇总主机、容器和 Prometheus 指标，优先展示重启、OOM 和资源热点。
          </Paragraph>
        </div>
      </div>

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
          <Card loading={loading} title="资源热点" className="ops-surface-card">
            <List
              dataSource={summary?.hotspots || []}
              locale={{ emptyText: '当前没有热点' }}
              renderItem={(item) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <Text strong>{item.name}</Text>
                      <Tag color={item.score >= 90 ? 'red' : item.score >= 70 ? 'orange' : 'blue'}>{item.score.toFixed(0)}</Tag>
                    </div>
                    <Paragraph style={{ marginBottom: 0 }}>{item.reason}</Paragraph>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
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
