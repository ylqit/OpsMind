import React, { useEffect, useMemo, useState } from 'react'
import { Button, Card, Col, Empty, List, Modal, Row, Space, Tag, Typography, message } from 'antd'
import {
  incidentsApi,
  recommendationsApi,
  tasksApi,
  type ArtifactContentResponse,
  type IncidentDetailResponse,
  type IncidentRecord,
  type RecommendationRecord,
  type TaskArtifact,
} from '@/api/client'

const { Paragraph, Text, Title } = Typography

interface IncidentListResponse {
  items: IncidentRecord[]
  total: number
}

interface PreviewState {
  artifact: TaskArtifact
  content: string
  filename: string
}

const artifactLabelMap: Record<string, string> = {
  manifest: 'YAML 草稿',
  report: '报告文件',
  json: 'JSON 结果',
  text: '文本内容',
}

export const RecommendationCenter: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewArtifactId, setPreviewArtifactId] = useState<string>('')
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selected, setSelected] = useState<IncidentDetailResponse | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)

  const selectedRecommendations = useMemo(() => selected?.recommendations || [], [selected])

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

  const refreshIncidentWithRetry = async (incident: IncidentRecord) => {
    for (let index = 0; index < 3; index += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 800))
      const detail = (await incidentsApi.get(incident.incident_id)) as IncidentDetailResponse
      setSelected(detail)
      if (detail.recommendations.length > 0) {
        break
      }
    }
  }

  const generate = async () => {
    if (!selected) {
      return
    }
    setGenerating(true)
    try {
      await recommendationsApi.generate({ incident_id: selected.incident.incident_id })
      message.success('建议生成任务已提交')
      await refreshIncidentWithRetry(selected.incident)
    } finally {
      setGenerating(false)
    }
  }

  const previewArtifact = async (artifact: TaskArtifact) => {
    setPreviewLoading(true)
    setPreviewArtifactId(artifact.artifact_id)
    try {
      const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
      setPreview({ artifact, content: response.content, filename: response.filename })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '读取草稿失败')
    } finally {
      setPreviewLoading(false)
      setPreviewArtifactId('')
    }
  }

  const downloadArtifact = (artifact: TaskArtifact) => {
    const url = tasksApi.getArtifactDownloadUrl(artifact.task_id, artifact.artifact_id)
    const link = document.createElement('a')
    link.href = url
    link.download = artifact.path.split(/[\\/]/).pop() || `${artifact.artifact_id}.txt`
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  useEffect(() => {
    void loadData()
  }, [])

  const renderArtifactActions = (artifact: TaskArtifact) => (
    <Space>
      <Button size="small" onClick={() => void previewArtifact(artifact)} loading={previewLoading && previewArtifactId === artifact.artifact_id}>
        预览
      </Button>
      <Button size="small" type="primary" ghost onClick={() => downloadArtifact(artifact)}>
        下载
      </Button>
    </Space>
  )

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>建议中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            面向已归档的异常生成建议条目和草稿文件，支持直接预览和下载 YAML 草稿。
          </Paragraph>
        </div>
        <Space>
          <Button type="primary" onClick={() => void generate()} loading={generating} disabled={!selected}>生成建议</Button>
          <Button onClick={() => void loadData()} loading={loading}>刷新详情</Button>
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
                dataSource={selectedRecommendations}
                locale={{ emptyText: '当前没有建议内容，可以先点击“生成建议”' }}
                renderItem={(item: RecommendationRecord) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space style={{ marginBottom: 8 }}>
                        <Tag color="blue">{item.kind}</Tag>
                        <Text strong>{item.observation}</Text>
                      </Space>
                      <Paragraph style={{ marginBottom: 8 }}>{item.recommendation}</Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 12 }}>{item.risk_note}</Paragraph>
                      <List
                        size="small"
                        dataSource={item.artifact_refs}
                        locale={{ emptyText: '暂无草稿产物' }}
                        renderItem={(artifact) => (
                          <List.Item actions={[renderArtifactActions(artifact)]}>
                            <div style={{ width: '100%' }}>
                              <Space style={{ marginBottom: 6 }}>
                                <Tag color="geekblue">{artifactLabelMap[artifact.kind] || artifact.kind}</Tag>
                                <Text code>{artifact.path.split(/[\\/]/).pop() || artifact.artifact_id}</Text>
                              </Space>
                              <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{artifact.preview || '暂无预览摘要'}</Paragraph>
                            </div>
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

      <Modal
        title={preview?.filename || '草稿预览'}
        open={Boolean(preview)}
        onCancel={() => setPreview(null)}
        footer={preview ? [
          <Button key="download" type="primary" onClick={() => downloadArtifact(preview.artifact)}>
            下载文件
          </Button>,
          <Button key="close" onClick={() => setPreview(null)}>
            关闭
          </Button>,
        ] : null}
        width={960}
      >
        <pre
          style={{
            margin: 0,
            maxHeight: '65vh',
            overflow: 'auto',
            padding: 16,
            borderRadius: 12,
            background: '#0f172a',
            color: '#e2e8f0',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {preview?.content || ''}
        </pre>
      </Modal>
    </div>
  )
}

export default RecommendationCenter
