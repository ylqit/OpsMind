import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, List, Row, Space, Tag, Typography } from 'antd'
import { incidentsApi, type IncidentDetailResponse, type IncidentRecord } from '@/api/client'

const { Paragraph, Text, Title } = Typography

interface IncidentListResponse {
  items: IncidentRecord[]
  total: number
}

interface EvidenceItem {
  layer?: string
  type?: string
  title?: string
  summary?: string
  metric?: string
  value?: unknown
  unit?: string
  reason?: string
  name?: string
  [key: string]: unknown
}

const layerMeta: Record<string, { title: string; color: string }> = {
  traffic: { title: '流量证据', color: 'blue' },
  resource: { title: '资源证据', color: 'orange' },
  diagnosis: { title: '关联判断', color: 'purple' },
  other: { title: '其他证据', color: 'default' },
}

const formatEvidenceValue = (item: EvidenceItem) => {
  if (item.value === undefined || item.value === null || item.value === '') {
    return '-'
  }
  if (typeof item.value === 'number') {
    return `${item.value}${item.unit ? ` ${item.unit}` : ''}`
  }
  return `${String(item.value)}${item.unit ? ` ${item.unit}` : ''}`
}

export const IncidentCenter: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetailResponse | null>(null)
  const [serviceKey, setServiceKey] = useState('unknown/root')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const groupedEvidence = useMemo(() => {
    const groups: Record<string, EvidenceItem[]> = {}
    const items = (selectedIncident?.incident.evidence_refs || []) as EvidenceItem[]
    for (const item of items) {
      const layer = typeof item.layer === 'string'
        ? item.layer
        : item.type === 'traffic_summary'
          ? 'traffic'
          : item.type === 'resource_summary' || item.type === 'hotspot'
            ? 'resource'
            : 'other'
      groups[layer] = groups[layer] || []
      groups[layer].push(item)
    }
    return groups
  }, [selectedIncident])

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
                <Space style={{ marginBottom: 12, flexWrap: 'wrap' }}>
                  <Tag color={selectedIncident.incident.severity === 'critical' ? 'red' : 'orange'}>{selectedIncident.incident.severity}</Tag>
                  <Text strong>{selectedIncident.incident.title}</Text>
                  <Tag color="geekblue">置信度 {Math.round(selectedIncident.incident.confidence * 100)}%</Tag>
                </Space>
                <Paragraph>{selectedIncident.incident.summary}</Paragraph>
                <Paragraph type="secondary">服务键：{selectedIncident.incident.service_key}</Paragraph>
                <Space wrap style={{ marginBottom: 16 }}>
                  {selectedIncident.incident.reasoning_tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </Space>

                <Card type="inner" title="证据链分层" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    {Object.entries(groupedEvidence).map(([layer, items]) => (
                      <Card key={layer} size="small" title={layerMeta[layer]?.title || layerMeta.other.title} extra={<Tag color={layerMeta[layer]?.color || layerMeta.other.color}>{items.length} 条</Tag>}>
                        <List
                          size="small"
                          dataSource={items}
                          renderItem={(item) => (
                            <List.Item>
                              <div style={{ width: '100%' }}>
                                <Space style={{ marginBottom: 6, flexWrap: 'wrap' }}>
                                  <Text strong>{String(item.title || item.name || item.metric || item.type || '证据项')}</Text>
                                  <Tag>{String(item.metric || item.type || 'metric')}</Tag>
                                  <Tag color="default">{formatEvidenceValue(item)}</Tag>
                                </Space>
                                <Paragraph style={{ marginBottom: 0 }}>{String(item.summary || item.reason || '-')}</Paragraph>
                              </div>
                            </List.Item>
                          )}
                        />
                      </Card>
                    ))}
                  </Space>
                </Card>

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
