import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Col, Empty, List, Modal, Row, Space, Tag, Typography, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
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

interface DiffSummary {
  fromFile: string
  toFile: string
  addedLines: number
  removedLines: number
  hunkCount: number
}

const artifactLabelMap: Record<string, string> = {
  manifest: 'YAML 草稿',
  diff: '变更差异',
  report: '报告文件',
  json: 'JSON 结果',
  text: '文本内容',
}

const getDiffLineClassName = (line: string) => {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return 'ops-artifact-line ops-artifact-line--file'
  }
  if (line.startsWith('@@')) {
    return 'ops-artifact-line ops-artifact-line--meta'
  }
  if (line.startsWith('+')) {
    return 'ops-artifact-line ops-artifact-line--added'
  }
  if (line.startsWith('-')) {
    return 'ops-artifact-line ops-artifact-line--removed'
  }
  return 'ops-artifact-line'
}

const buildDiffSummary = (content: string): DiffSummary => {
  const lines = content.split('\n')
  let fromFile = '未识别基线文件'
  let toFile = '未识别建议文件'
  let addedLines = 0
  let removedLines = 0
  let hunkCount = 0

  for (const line of lines) {
    if (line.startsWith('--- ')) {
      fromFile = line.replace('--- ', '').trim() || fromFile
      continue
    }
    if (line.startsWith('+++ ')) {
      toFile = line.replace('+++ ', '').trim() || toFile
      continue
    }
    if (line.startsWith('@@')) {
      hunkCount += 1
      continue
    }
    if (line.startsWith('+')) {
      addedLines += 1
      continue
    }
    if (line.startsWith('-')) {
      removedLines += 1
    }
  }

  return { fromFile, toFile, addedLines, removedLines, hunkCount }
}

export const RecommendationCenter: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewArtifactId, setPreviewArtifactId] = useState<string>('')
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [selected, setSelected] = useState<IncidentDetailResponse | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const initialQueryHandledRef = useRef(false)

  const selectedRecommendations = useMemo(() => selected?.recommendations || [], [selected])
  const isDiffPreview = preview?.artifact.kind === 'diff'
  const copyLabel = preview?.artifact.kind === 'manifest' ? '复制 YAML' : '复制内容'
  const diffSummary = useMemo(() => (isDiffPreview && preview ? buildDiffSummary(preview.content) : null), [isDiffPreview, preview])

  const updateRouteState = (incidentId?: string, artifact?: TaskArtifact | null) => {
    const nextParams = new URLSearchParams()
    if (incidentId) {
      nextParams.set('incidentId', incidentId)
    }
    if (artifact) {
      nextParams.set('taskId', artifact.task_id)
      nextParams.set('artifactId', artifact.artifact_id)
    }
    setSearchParams(nextParams, { replace: true })
  }

  const previewArtifact = async (artifact: TaskArtifact, incidentId?: string) => {
    setPreviewLoading(true)
    setPreviewArtifactId(artifact.artifact_id)
    try {
      const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
      setPreview({ artifact, content: response.content, filename: response.filename })
      updateRouteState(incidentId || selected?.incident.incident_id, artifact)
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

  const copyPreviewContent = async () => {
    if (!preview) {
      return
    }
    try {
      await navigator.clipboard.writeText(preview.content)
      message.success(preview.artifact.kind === 'manifest' ? 'YAML 已复制' : '内容已复制')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复制失败')
    }
  }

  const copyArtifactContent = async (artifact: TaskArtifact) => {
    try {
      const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
      await navigator.clipboard.writeText(response.content)
      message.success(artifact.kind === 'manifest' ? 'YAML 已复制' : '内容已复制')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复制失败')
    }
  }

  const loadIncidentDetail = async (incidentId: string) => {
    const detail = (await incidentsApi.get(incidentId)) as IncidentDetailResponse
    setSelected(detail)
    return detail
  }

  const tryOpenArtifactFromQuery = async (detail: IncidentDetailResponse) => {
    const artifactId = searchParams.get('artifactId')
    const taskId = searchParams.get('taskId')
    if (!artifactId || !taskId) {
      return
    }
    const artifact = detail.recommendations
      .flatMap((item) => item.artifact_refs)
      .find((item) => item.artifact_id === artifactId && item.task_id === taskId)
    if (artifact) {
      await previewArtifact(artifact, detail.incident.incident_id)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const listResponse = (await incidentsApi.list()) as IncidentListResponse
      setIncidents(listResponse.items)
      if (!listResponse.items.length) {
        setSelected(null)
        return
      }
      const targetIncidentId = searchParams.get('incidentId') || listResponse.items[0].incident_id
      const detail = await loadIncidentDetail(targetIncidentId)
      if (!initialQueryHandledRef.current) {
        initialQueryHandledRef.current = true
        await tryOpenArtifactFromQuery(detail)
      }
    } finally {
      setLoading(false)
    }
  }

  const selectIncident = async (incident: IncidentRecord) => {
    const detail = await loadIncidentDetail(incident.incident_id)
    updateRouteState(detail.incident.incident_id, null)
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

  useEffect(() => {
    void loadData()
  }, [])

  const renderArtifactActions = (artifact: TaskArtifact) => (
    <Space>
      <Button size="small" onClick={() => void previewArtifact(artifact, selected?.incident.incident_id)} loading={previewLoading && previewArtifactId === artifact.artifact_id}>
        预览
      </Button>
      {artifact.kind === 'manifest' ? (
        <Button size="small" onClick={() => void copyArtifactContent(artifact)}>
          复制 YAML
        </Button>
      ) : null}
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
            面向已归档的异常生成建议条目和草稿文件，支持自动打开 YAML 草稿和变更差异预览。
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
                                <Tag color={artifact.kind === 'diff' ? 'purple' : 'geekblue'}>{artifactLabelMap[artifact.kind] || artifact.kind}</Tag>
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
        onCancel={() => {
          setPreview(null)
          updateRouteState(selected?.incident.incident_id, null)
        }}
        footer={preview ? [
          <Button key="copy" onClick={() => void copyPreviewContent()}>
            {copyLabel}
          </Button>,
          <Button key="download" type="primary" onClick={() => downloadArtifact(preview.artifact)}>
            下载文件
          </Button>,
          <Button key="close" onClick={() => {
            setPreview(null)
            updateRouteState(selected?.incident.incident_id, null)
          }}>
            关闭
          </Button>,
        ] : null}
        width={960}
      >
        {isDiffPreview && diffSummary ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="ops-diff-summary">
              <div className="ops-diff-summary__files">
                <div className="ops-diff-summary__file-card">
                  <span className="ops-diff-summary__label">基线文件</span>
                  <Text code>{diffSummary.fromFile}</Text>
                </div>
                <div className="ops-diff-summary__file-card">
                  <span className="ops-diff-summary__label">建议文件</span>
                  <Text code>{diffSummary.toFile}</Text>
                </div>
              </div>
              <Space wrap>
                <Tag color="green">新增 {diffSummary.addedLines} 行</Tag>
                <Tag color="red">删除 {diffSummary.removedLines} 行</Tag>
                <Tag color="blue">变更块 {diffSummary.hunkCount} 处</Tag>
              </Space>
            </div>
            <div className="ops-artifact-viewer ops-artifact-viewer--diff">
              {preview.content.split('\n').map((line, index) => (
                <div key={`${index}-${line}`} className={getDiffLineClassName(line)}>
                  <span className="ops-artifact-line__number">{index + 1}</span>
                  <span className="ops-artifact-line__content">{line || ' '}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <pre className="ops-artifact-viewer">{preview?.content || ''}</pre>
        )}
      </Modal>
    </div>
  )
}

export default RecommendationCenter
