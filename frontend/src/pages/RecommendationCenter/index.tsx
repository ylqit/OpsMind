import React, { useEffect, useState } from 'react'
import { Button, Card, Col, Empty, List, Row, Space, Tag, Typography } from 'antd'
import { incidentsApi, recommendationsApi, type IncidentDetailResponse, type IncidentRecord } from '@/api/client'

const { Paragraph, Text, Title } = Typography

interface IncidentListResponse {
  items: IncidentRecord[]
  total: number
}

export const RecommendationCenter: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selected, setSelected] = useState<IncidentDetailResponse | null>(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const listResponse = (await incidentsApi.list()) as IncidentListResponse
      setIncidents(listResponse.items)
      if (listResponse.items[0]) {
        const detail = (await incidentsApi.get(listResponse.items[0].incident_id)) as IncidentDetailResponse
        setSelected(detail)
      } else {
        setSelected(null)
      }
    } finally {
      setLoading(false)
    }
  }

  const selectIncident = async (incident: IncidentRecord) => {
    const detail = (await incidentsApi.get(incident.incident_id)) as IncidentDetailResponse
    setSelected(detail)
  }

  const generate = async () => {
    if (!selected) {
      return
    }
    setGenerating(true)
    try {
      await recommendationsApi.generate({ incident_id: selected.incident.incident_id })
      await selectIncident(selected.incident)
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>建议中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            面向已归档的异常生成建议条目和草稿文件，输出人工可审阅的配置建议。
          </Paragraph>
        </div>
        <Space>
          <Button type="primary" onClick={() => void generate()} loading={generating} disabled={!selected}>生成建议</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="可选异常" loading={loading} className="ops-surface-card">
            <List
              dataSource={incidents}
              locale={{ emptyText: '暂无可用异常' }}
              renderItem={(incident) => (
                <List.Item onClick={() => void selectIncident(incident)} style={{ cursor: 'pointer' }}>
                  <div style={{ width: '100%' }}>
                    <Space style={{ marginBottom: 8 }}>
                      <Tag color={incident.severity === 'critical' ? 'red' : 'orange'}>{incident.severity}</Tag>
                      <Text strong>{incident.title}</Text>
                    </Space>
                    <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>{incident.summary}</Paragraph>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card title="建议详情" loading={loading} className="ops-surface-card">
            {!selected ? (
              <Empty description="请选择异常后查看建议" />
            ) : (
              <List
                dataSource={selected.recommendations}
                locale={{ emptyText: '当前没有建议内容，可以先点击“生成建议”' }}
                renderItem={(item) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space style={{ marginBottom: 8 }}>
                        <Tag color="blue">{item.kind}</Tag>
                        <Text strong>{item.observation}</Text>
                      </Space>
                      <Paragraph style={{ marginBottom: 8 }}>{item.recommendation}</Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 8 }}>{item.risk_note}</Paragraph>
                      <List
                        size="small"
                        dataSource={item.artifact_refs}
                        locale={{ emptyText: '暂无草稿产物' }}
                        renderItem={(artifact) => (
                          <List.Item>
                            <Text code>{String(artifact.path || artifact.artifact_id || '-')}</Text>
                          </List.Item>
                        )}
                      />
                    </div>
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default RecommendationCenter
