import React, { useEffect, useMemo, useState } from 'react'
import { Button, Card, Col, Empty, List, Row, Segmented, Space, Tag, Typography, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
import {
  incidentsApi,
  recommendationsApi,
  tasksApi,
  type ArtifactContentResponse,
  type IncidentDetailResponse,
  type IncidentRecord,
  type RecommendationAIReviewResponse,
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

interface ArtifactGroup {
  baseline?: TaskArtifact
  recommended?: TaskArtifact
  diff?: TaskArtifact
}

interface BundleArtifactContent {
  artifact: TaskArtifact
  filename: string
  content: string
}

const artifactLabelMap: Record<string, string> = {
  manifest: 'YAML 草稿',
  diff: '变更差异',
  report: '报告文件',
  json: 'JSON 结果',
  text: '文本内容',
}

const getArtifactFilename = (artifact: TaskArtifact) => {
  return artifact.path.split(/[\\/]/).pop() || `${artifact.artifact_id}.txt`
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

const getRiskLevelColor = (riskLevel: string) => {
  if (riskLevel === 'high') {
    return 'red'
  }
  if (riskLevel === 'medium') {
    return 'orange'
  }
  return 'green'
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
    if (line.startsWith('+') && !line.startsWith('+++')) {
      addedLines += 1
      continue
    }
    if (line.startsWith('-') && !line.startsWith('---')) {
      removedLines += 1
    }
  }

  return { fromFile, toFile, addedLines, removedLines, hunkCount }
}

// 把同一条建议产出的多个文件整理成稳定的三视图分组。
const buildArtifactGroup = (artifacts: TaskArtifact[]): ArtifactGroup => {
  const group: ArtifactGroup = {}
  for (const artifact of artifacts) {
    const filename = getArtifactFilename(artifact)
    if (artifact.kind === 'diff' && !group.diff) {
      group.diff = artifact
      continue
    }
    if (artifact.kind === 'manifest' && filename.includes('-baseline') && !group.baseline) {
      group.baseline = artifact
      continue
    }
    if (artifact.kind === 'manifest' && filename.includes('-recommended') && !group.recommended) {
      group.recommended = artifact
      continue
    }
    if (artifact.kind === 'manifest' && !group.recommended) {
      group.recommended = artifact
    }
  }
  if (!group.baseline && group.recommended) {
    group.baseline = group.recommended
  }
  return group
}

const detectViewKey = (artifact: TaskArtifact): 'baseline' | 'recommended' | 'diff' => {
  if (artifact.kind === 'diff') {
    return 'diff'
  }
  const filename = getArtifactFilename(artifact)
  if (filename.includes('-baseline')) {
    return 'baseline'
  }
  return 'recommended'
}

const getPrimaryArtifact = (artifacts: TaskArtifact[]): TaskArtifact | null => {
  const group = buildArtifactGroup(artifacts)
  return group.recommended || group.diff || group.baseline || artifacts[0] || null
}

const findRecommendationByArtifact = (
  recommendations: RecommendationRecord[],
  artifactId: string,
  taskId: string,
): RecommendationRecord | null => {
  return (
    recommendations.find((item) =>
      item.artifact_refs.some((artifact) => artifact.artifact_id === artifactId && artifact.task_id === taskId),
    ) || null
  )
}

// 导出与复制时保持稳定顺序：建议稿 -> 基线 -> diff -> 其他产物。
const buildBundleArtifacts = (recommendation: RecommendationRecord): TaskArtifact[] => {
  const group = buildArtifactGroup(recommendation.artifact_refs)
  const preferred = [group.recommended, group.baseline, group.diff].filter(Boolean) as TaskArtifact[]
  const seen = new Set<string>()
  const merged: TaskArtifact[] = []
  for (const artifact of [...preferred, ...recommendation.artifact_refs]) {
    if (seen.has(artifact.artifact_id)) {
      continue
    }
    seen.add(artifact.artifact_id)
    merged.push(artifact)
  }
  return merged
}

const getFenceLanguage = (artifact: TaskArtifact) => {
  if (artifact.kind === 'manifest') {
    return 'yaml'
  }
  if (artifact.kind === 'diff') {
    return 'diff'
  }
  return 'text'
}

const downloadTextFile = (filename: string, content: string, mimeType: string = 'text/plain;charset=utf-8') => {
  const blob = new Blob([content], { type: mimeType })
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

// 兼容浏览器权限限制，clipboard 不可用时回退到 execCommand。
const copyTextSafely = async (text: string) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) {
    throw new Error('当前浏览器不支持复制，请手动复制')
  }
}

const buildBundleMarkdown = (
  recommendation: RecommendationRecord,
  incident: IncidentRecord | undefined,
  bundleItems: BundleArtifactContent[],
) => {
  const exportedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const lines: string[] = [
    '# opsMind 建议草稿导出',
    '',
    `- 导出时间: ${exportedAt}`,
    `- incident_id: ${recommendation.incident_id}`,
    `- recommendation_id: ${recommendation.recommendation_id}`,
    `- 建议类型: ${recommendation.kind}`,
    `- 服务键: ${incident?.service_key || '-'}`,
    `- 说明: ${recommendation.recommendation}`,
    '',
  ]

  bundleItems.forEach((item, index) => {
    lines.push(`## ${index + 1}. ${(artifactLabelMap[item.artifact.kind] || item.artifact.kind)} · ${item.filename}`)
    lines.push('')
    lines.push('```' + getFenceLanguage(item.artifact))
    lines.push(item.content)
    lines.push('```')
    lines.push('')
  })

  return lines.join('\n')
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
  const [activeArtifactView, setActiveArtifactView] = useState<'baseline' | 'recommended' | 'diff'>('recommended')
  const [activeRecommendationId, setActiveRecommendationId] = useState<string>('')
  const [previewCopying, setPreviewCopying] = useState(false)
  const [artifactCopyingId, setArtifactCopyingId] = useState('')
  const [bundleCopyingId, setBundleCopyingId] = useState('')
  const [bundleExportingId, setBundleExportingId] = useState('')
  const [aiReviewLoadingId, setAiReviewLoadingId] = useState('')
  const [aiReviewByRecommendationId, setAiReviewByRecommendationId] = useState<Record<string, RecommendationAIReviewResponse>>({})

  const selectedRecommendations = useMemo(() => selected?.recommendations || [], [selected])
  const activeRecommendation = useMemo(
    () => selectedRecommendations.find((item) => item.recommendation_id === activeRecommendationId) || null,
    [activeRecommendationId, selectedRecommendations],
  )
  const previewArtifactGroup = useMemo(
    () => (activeRecommendation ? buildArtifactGroup(activeRecommendation.artifact_refs) : null),
    [activeRecommendation],
  )
  const activeAiReview = useMemo(
    () => (activeRecommendation ? aiReviewByRecommendationId[activeRecommendation.recommendation_id] || null : null),
    [activeRecommendation, aiReviewByRecommendationId],
  )
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

  const previewArtifact = async (artifact: TaskArtifact, recommendationId: string, incidentId?: string) => {
    setPreviewLoading(true)
    setPreviewArtifactId(artifact.artifact_id)
    try {
      const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
      setPreview({ artifact, content: response.content, filename: response.filename })
      setActiveArtifactView(detectViewKey(artifact))
      setActiveRecommendationId(recommendationId)
      updateRouteState(incidentId || selected?.incident.incident_id, artifact)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '读取草稿失败')
    } finally {
      setPreviewLoading(false)
      setPreviewArtifactId('')
    }
  }

  const openRecommendationWorkspace = async (recommendation: RecommendationRecord, preferredArtifact?: TaskArtifact) => {
    const artifact = preferredArtifact || getPrimaryArtifact(recommendation.artifact_refs)
    setActiveRecommendationId(recommendation.recommendation_id)
    if (!artifact) {
      setPreview(null)
      updateRouteState(selected?.incident.incident_id, null)
      return
    }
    await previewArtifact(artifact, recommendation.recommendation_id, selected?.incident.incident_id)
  }

  const switchPreviewView = async (viewKey: string) => {
    if (!previewArtifactGroup || !selected || !activeRecommendationId) {
      return
    }
    const artifact = viewKey === 'baseline'
      ? previewArtifactGroup.baseline
      : viewKey === 'diff'
        ? previewArtifactGroup.diff
        : previewArtifactGroup.recommended
    if (!artifact) {
      return
    }
    await previewArtifact(artifact, activeRecommendationId, selected.incident.incident_id)
  }

  const downloadArtifact = (artifact: TaskArtifact) => {
    const url = tasksApi.getArtifactDownloadUrl(artifact.task_id, artifact.artifact_id)
    const link = document.createElement('a')
    link.href = url
    link.download = getArtifactFilename(artifact)
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  const loadBundleContents = async (recommendation: RecommendationRecord): Promise<BundleArtifactContent[]> => {
    const artifacts = buildBundleArtifacts(recommendation)
    const results = await Promise.all(
      artifacts.map(async (artifact) => {
        const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
        return {
          artifact,
          filename: response.filename,
          content: response.content,
        }
      }),
    )
    return results
  }

  const copyRecommendationBundle = async (recommendation: RecommendationRecord) => {
    if (!recommendation.artifact_refs.length) {
      message.warning('当前建议没有可复制的草稿')
      return
    }
    setBundleCopyingId(recommendation.recommendation_id)
    try {
      const bundleItems = await loadBundleContents(recommendation)
      const bundleContent = buildBundleMarkdown(recommendation, selected?.incident, bundleItems)
      await copyTextSafely(bundleContent)
      message.success(`整套草稿已复制（${bundleItems.length} 份产物）`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复制整套草稿失败')
    } finally {
      setBundleCopyingId('')
    }
  }

  const exportRecommendationBundle = async (recommendation: RecommendationRecord) => {
    if (!recommendation.artifact_refs.length) {
      message.warning('当前建议没有可导出的草稿')
      return
    }
    setBundleExportingId(recommendation.recommendation_id)
    try {
      const bundleItems = await loadBundleContents(recommendation)
      const bundleContent = buildBundleMarkdown(recommendation, selected?.incident, bundleItems)
      downloadTextFile(`recommendation-${recommendation.recommendation_id}.md`, bundleContent, 'text/markdown;charset=utf-8')
      message.success(`整套草稿已导出（${bundleItems.length} 份产物）`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导出整套草稿失败')
    } finally {
      setBundleExportingId('')
    }
  }

  const copyPreviewContent = async () => {
    if (!preview) {
      return
    }
    setPreviewCopying(true)
    try {
      await copyTextSafely(preview.content)
      message.success(preview.artifact.kind === 'manifest' ? 'YAML 已复制' : '内容已复制')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复制失败')
    } finally {
      setPreviewCopying(false)
    }
  }

  const copyArtifactContent = async (artifact: TaskArtifact) => {
    setArtifactCopyingId(artifact.artifact_id)
    try {
      const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
      await copyTextSafely(response.content)
      message.success(artifact.kind === 'manifest' ? 'YAML 已复制' : '内容已复制')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复制失败')
    } finally {
      setArtifactCopyingId('')
    }
  }

  const loadIncidentDetail = async (incidentId: string) => {
    const detail = (await incidentsApi.get(incidentId)) as IncidentDetailResponse
    setSelected(detail)
    setAiReviewByRecommendationId({})
    return detail
  }

  // 页内工作区需要始终有一个默认落点，优先打开建议稿，其次才是 diff 或基线。
  const openDefaultRecommendation = async (detail: IncidentDetailResponse) => {
    const firstRecommendation = detail.recommendations[0]
    if (!firstRecommendation) {
      setActiveRecommendationId('')
      setPreview(null)
      updateRouteState(detail.incident.incident_id, null)
      return
    }
    const artifact = getPrimaryArtifact(firstRecommendation.artifact_refs)
    setActiveRecommendationId(firstRecommendation.recommendation_id)
    if (!artifact) {
      updateRouteState(detail.incident.incident_id, null)
      return
    }
    await previewArtifact(artifact, firstRecommendation.recommendation_id, detail.incident.incident_id)
  }

  // 当页面带着 incidentId/taskId/artifactId 进入时，优先恢复到指定草稿视图。
  const tryOpenArtifactFromQuery = async (detail: IncidentDetailResponse) => {
    const artifactId = searchParams.get('artifactId')
    const taskId = searchParams.get('taskId')
    if (!artifactId || !taskId) {
      await openDefaultRecommendation(detail)
      return
    }
    const recommendation = findRecommendationByArtifact(detail.recommendations, artifactId, taskId)
    const artifact = recommendation?.artifact_refs.find((item) => item.artifact_id === artifactId && item.task_id === taskId)
    if (artifact && recommendation) {
      await previewArtifact(artifact, recommendation.recommendation_id, detail.incident.incident_id)
      return
    }
    await openDefaultRecommendation(detail)
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const listResponse = (await incidentsApi.list()) as IncidentListResponse
      setIncidents(listResponse.items)
      if (!listResponse.items.length) {
        setSelected(null)
        setPreview(null)
        setActiveRecommendationId('')
        setAiReviewByRecommendationId({})
        return
      }
      const targetIncidentId = searchParams.get('incidentId') || listResponse.items[0].incident_id
      const detail = await loadIncidentDetail(targetIncidentId)
      await tryOpenArtifactFromQuery(detail)
    } finally {
      setLoading(false)
    }
  }

  const selectIncident = async (incident: IncidentRecord) => {
    const detail = await loadIncidentDetail(incident.incident_id)
    await openDefaultRecommendation(detail)
  }

  const refreshIncidentWithRetry = async (incident: IncidentRecord) => {
    for (let index = 0; index < 3; index += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 800))
      const detail = (await incidentsApi.get(incident.incident_id)) as IncidentDetailResponse
      setSelected(detail)
      if (detail.recommendations.length > 0) {
        await tryOpenArtifactFromQuery(detail)
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

  const reviewRecommendationWithAi = async (recommendation: RecommendationRecord) => {
    setAiReviewLoadingId(recommendation.recommendation_id)
    try {
      const response = (await recommendationsApi.aiReview(recommendation.recommendation_id)) as RecommendationAIReviewResponse
      setAiReviewByRecommendationId((previous) => ({
        ...previous,
        [recommendation.recommendation_id]: response,
      }))
      message.success('AI 复核已生成')
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'AI 复核失败')
    } finally {
      setAiReviewLoadingId('')
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const renderArtifactActions = (artifact: TaskArtifact, recommendation: RecommendationRecord) => (
    <Space>
      <Button
        size="small"
        type={preview?.artifact.artifact_id === artifact.artifact_id ? 'primary' : 'default'}
        onClick={() => void previewArtifact(artifact, recommendation.recommendation_id, selected?.incident.incident_id)}
        loading={previewLoading && previewArtifactId === artifact.artifact_id}
      >
        打开工作区
      </Button>
      {artifact.kind === 'manifest' ? (
        <Button size="small" loading={artifactCopyingId === artifact.artifact_id} onClick={() => void copyArtifactContent(artifact)}>
          复制 YAML
        </Button>
      ) : null}
      <Button size="small" type="primary" ghost onClick={() => downloadArtifact(artifact)}>
        下载
      </Button>
    </Space>
  )

  const previewViewOptions = [
    previewArtifactGroup?.baseline ? { label: '基线', value: 'baseline' } : null,
    previewArtifactGroup?.recommended ? { label: '建议', value: 'recommended' } : null,
    previewArtifactGroup?.diff ? { label: 'Diff', value: 'diff' } : null,
  ].filter(Boolean) as Array<{ label: string; value: string }>

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>建议中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            以页内工作区方式查看建议草稿，支持直接切换基线、建议和差异视图，不再依赖弹窗完成主流程。
          </Paragraph>
        </div>
        <Space>
          <Button type="primary" onClick={() => void generate()} loading={generating} disabled={!selected}>生成建议</Button>
          <Button onClick={() => void loadData()} loading={loading}>刷新详情</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={7}>
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
        <Col xs={24} xl={17}>
          <div className="ops-recommendation-layout">
            <Card title="建议详情" loading={loading} className="ops-surface-card">
              {!selected ? (
                <Empty description="请选择异常后查看建议" />
              ) : (
                <List
                  dataSource={selectedRecommendations}
                  locale={{ emptyText: '当前没有建议内容，可以先点击“生成建议”' }}
                  renderItem={(item: RecommendationRecord) => {
                    const isActiveRecommendation = item.recommendation_id === activeRecommendationId
                    return (
                      <List.Item className={isActiveRecommendation ? 'ops-recommendation-item ops-recommendation-item--active' : 'ops-recommendation-item'}>
                        <div style={{ width: '100%' }}>
                          <Space style={{ marginBottom: 8 }}>
                            <Tag color="blue">{item.kind}</Tag>
                            <Text strong>{item.observation}</Text>
                            {isActiveRecommendation ? <Tag color="cyan">当前草稿</Tag> : null}
                            {aiReviewByRecommendationId[item.recommendation_id] ? <Tag color="purple">已 AI 复核</Tag> : null}
                          </Space>
                          <Paragraph style={{ marginBottom: 8 }}>{item.recommendation}</Paragraph>
                          <Paragraph type="secondary" style={{ marginBottom: 12 }}>{item.risk_note}</Paragraph>
                          <div className="ops-recommendation-item__toolbar">
                            <Space wrap>
                              <Button onClick={() => void openRecommendationWorkspace(item)} disabled={!item.artifact_refs.length}>
                                打开页内工作区
                              </Button>
                              <Button
                                onClick={() => void reviewRecommendationWithAi(item)}
                                loading={aiReviewLoadingId === item.recommendation_id}
                              >
                                AI 复核
                              </Button>
                              <Button
                                onClick={() => void copyRecommendationBundle(item)}
                                loading={bundleCopyingId === item.recommendation_id}
                                disabled={!item.artifact_refs.length}
                              >
                                复制整套草稿
                              </Button>
                              <Button
                                type="primary"
                                ghost
                                onClick={() => void exportRecommendationBundle(item)}
                                loading={bundleExportingId === item.recommendation_id}
                                disabled={!item.artifact_refs.length}
                              >
                                导出整套草稿
                              </Button>
                            </Space>
                            <Text type="secondary">共 {item.artifact_refs.length} 份产物</Text>
                          </div>
                          <List
                            size="small"
                            dataSource={item.artifact_refs}
                            locale={{ emptyText: '暂无草稿产物' }}
                            renderItem={(artifact) => (
                              <List.Item actions={[renderArtifactActions(artifact, item)]}>
                                <div style={{ width: '100%' }}>
                                  <Space style={{ marginBottom: 6 }}>
                                    <Tag color={artifact.kind === 'diff' ? 'purple' : 'geekblue'}>{artifactLabelMap[artifact.kind] || artifact.kind}</Tag>
                                    <Text code>{getArtifactFilename(artifact)}</Text>
                                  </Space>
                                  <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{artifact.preview || '暂无预览摘要'}</Paragraph>
                                </div>
                              </List.Item>
                            )}
                          />
                        </div>
                      </List.Item>
                    )
                  }}
                />
              )}
            </Card>

            <Card
              title="草稿工作区"
              className="ops-surface-card"
              extra={preview && activeRecommendation ? (
                <Space wrap>
                  <Button onClick={() => void copyPreviewContent()} loading={previewCopying}>{copyLabel}</Button>
                  <Button
                    onClick={() => void reviewRecommendationWithAi(activeRecommendation)}
                    loading={aiReviewLoadingId === activeRecommendation.recommendation_id}
                  >
                    AI 复核
                  </Button>
                  <Button
                    onClick={() => void copyRecommendationBundle(activeRecommendation)}
                    loading={bundleCopyingId === activeRecommendation.recommendation_id}
                  >
                    复制整套草稿
                  </Button>
                  <Button
                    onClick={() => void exportRecommendationBundle(activeRecommendation)}
                    loading={bundleExportingId === activeRecommendation.recommendation_id}
                  >
                    导出整套草稿
                  </Button>
                  <Button type="primary" onClick={() => downloadArtifact(preview.artifact)}>下载当前视图</Button>
                </Space>
              ) : null}
            >
              {!preview || !activeRecommendation ? (
                <Empty description="请选择建议产物后在这里查看基线、建议和差异内容" />
              ) : (
                <div className="ops-recommendation-workspace">
                  <div className="ops-recommendation-workspace__header">
                    <div>
                      <Space wrap style={{ marginBottom: 8 }}>
                        <Tag color="blue">{activeRecommendation.kind}</Tag>
                        <Text strong>{activeRecommendation.observation}</Text>
                      </Space>
                      <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.68)' }}>
                        {activeRecommendation.recommendation}
                      </Paragraph>
                    </div>
                    <div className="ops-recommendation-workspace__meta">
                      <Text code>{preview.filename}</Text>
                      <Text type="secondary">当前视图：{activeArtifactView === 'baseline' ? '基线' : activeArtifactView === 'diff' ? 'Diff' : '建议'}</Text>
                    </div>
                  </div>

                  {previewViewOptions.length > 1 ? (
                    <Segmented block options={previewViewOptions} value={activeArtifactView} onChange={(value) => void switchPreviewView(String(value))} />
                  ) : null}

                  {activeAiReview ? (
                    <Card type="inner" title="AI 复核" size="small">
                      <Space wrap style={{ marginBottom: 10 }}>
                        <Tag color={getRiskLevelColor(activeAiReview.risk_level)}>风险等级：{activeAiReview.risk_level}</Tag>
                        <Tag color="geekblue">置信度：{Math.round(activeAiReview.confidence * 100)}%</Tag>
                        <Tag>{activeAiReview.parse_mode === 'json' ? '结构化输出' : '降级输出'}</Tag>
                      </Space>
                      <Paragraph style={{ marginBottom: 8 }}>{activeAiReview.summary}</Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 12 }}>{activeAiReview.risk_assessment}</Paragraph>
                      <Text strong style={{ display: 'block', marginBottom: 6 }}>验证检查</Text>
                      <List
                        size="small"
                        dataSource={activeAiReview.validation_checks}
                        locale={{ emptyText: '暂无' }}
                        renderItem={(item) => <List.Item>{item}</List.Item>}
                        style={{ marginBottom: 8 }}
                      />
                      <Text strong style={{ display: 'block', marginBottom: 6 }}>回滚步骤</Text>
                      <List
                        size="small"
                        dataSource={activeAiReview.rollback_plan}
                        locale={{ emptyText: '暂无' }}
                        renderItem={(item) => <List.Item>{item}</List.Item>}
                        style={{ marginBottom: 8 }}
                      />
                      <Text strong style={{ display: 'block', marginBottom: 6 }}>证据引用</Text>
                      <List
                        size="small"
                        dataSource={activeAiReview.evidence_citations}
                        locale={{ emptyText: '暂无' }}
                        renderItem={(item) => (
                          <List.Item>
                            <Text code>{item}</Text>
                          </List.Item>
                        )}
                      />
                    </Card>
                  ) : null}

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
                    <pre className="ops-artifact-viewer">{preview.content}</pre>
                  )}
                </div>
              )}
            </Card>
          </div>
        </Col>
      </Row>
    </div>
  )
}

export default RecommendationCenter
