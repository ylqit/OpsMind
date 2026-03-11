import React, { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, List, Row, Space, Tag, Timeline, Typography } from 'antd'
import { incidentsApi, type IncidentDetailResponse, type IncidentRecord } from '@/api/client'

const { Paragraph, Text, Title } = Typography

interface IncidentListResponse {
  items: IncidentRecord[]
  total: number
}

export const IncidentCenter: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetailResponse | null>(null)
  const [serviceKey, setServiceKey] = useState('unknown/root')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const loadIncidents = async () => {
    setLoading(true)
    setError('')
    try {
      const response = (await incidentsApi.list()) as IncidentListResponse
      setIncidents(response.items)
      if (response.items[0]) {
        await loadIncidentDetail(response.items[0].incident_id)
      } else {
        setSelectedIncident(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载异常失败')
    } finally {
      setLoading(false)
    }
  }

  const loadIncidentDetail = async (incidentId: string) => {
    const response = (await incidentsApi.get(incidentId)) as IncidentDetailResponse
    setSelectedIncident(response)
  }

  const createIncidentTask = async () => {
    setCreating(true)
    try {
      await incidentsApi.analyze({ service_key: serviceKey || undefined, time_window: '1h' })
      await loadIncidents()
    } finally {
      setCreating(false)
    }
  }

  useEffect(() => {
    void loadIncidents()
  }, [])

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>异常中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            按服务维度收拢症状、证据链和建议入口，用同一个视图完成排查与判断。
          </Paragraph>
        </div>
        <Space wrap>
          <Input value={serviceKey} onChange={(event) => setServiceKey(event.target.value)} placeholder="service_key，例如 docker/nginx" style={{ width: 220 }} />
          <Button type="primary" loading={creating} onClick={() => void createIncidentTask()}>发起分析</Button>
        </Space>
      </div>

      {error ? <Alert type="error" showIcon message="异常中心加载失败" description={error} style={{ marginBottom: 16 }} /> : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card title="异常列表" loading={loading} className="ops-surface-card">
            <List
              dataSource={incidents}
              locale={{ emptyText: '暂无异常记录' }}
              renderItem={(incident) => (
                <List.Item onClick={() => void loadIncidentDetail(incident.incident_id)} style={{ cursor: 'pointer' }}>
                  <div style={{ width: '100%' }}>
                    <Space style={{ marginBottom: 8 }}>
                      <Tag color={incident.severity === 'critical' ? 'red' : incident.severity === 'warning' ? 'orange' : 'blue'}>{incident.severity}</Tag>
                      <Text strong>{incident.title}</Text>
                    </Space>
                    <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 4 }}>{incident.summary}</Paragraph>
                    <Text type="secondary">{incident.service_key}</Text>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card title="异常详情" loading={loading} className="ops-surface-card">
            {!selectedIncident ? (
              <Empty description="请选择一个异常或先发起分析" />
            ) : (
              <div>
                <Space style={{ marginBottom: 12 }}>
                  <Tag color={selectedIncident.incident.severity === 'critical' ? 'red' : 'orange'}>{selectedIncident.incident.severity}</Tag>
                  <Text strong>{selectedIncident.incident.title}</Text>
                </Space>
                <Paragraph>{selectedIncident.incident.summary}</Paragraph>
                <Paragraph type="secondary">服务键：{selectedIncident.incident.service_key}</Paragraph>
                <Timeline
                  items={selectedIncident.incident.evidence_refs.map((item, index) => ({
                    children: `${String(item.metric || item.type || `evidence-${index}`)}: ${String(item.value || item.reason || '-')}`,
                  }))}
                />
                <Card type="inner" title="推荐动作" style={{ marginBottom: 16 }}>
                  <List
                    dataSource={selectedIncident.incident.recommended_actions}
                    locale={{ emptyText: '暂无建议动作' }}
                    renderItem={(item) => <List.Item>{item}</List.Item>}
                  />
                </Card>
                <Card type="inner" title="已生成建议">
                  <List
                    dataSource={selectedIncident.recommendations}
                    locale={{ emptyText: '当前还没有建议内容' }}
                    renderItem={(item) => (
                      <List.Item>
                        <div>
                          <Tag>{item.kind}</Tag>
                          <Text>{item.recommendation}</Text>
                        </div>
                      </List.Item>
                    )}
                  />
                </Card>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default IncidentCenter
