import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Drawer, Empty, Input, List, Modal, Row, Segmented, Select, Space, Tag, Typography, message } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  aiApi,
  type AIAssistantStatusResponse,
  type ClaimRecord,
  incidentsApi,
  recommendationsApi,
  tasksApi,
  type ArtifactContentResponse,
  type IncidentDetailResponse,
  type IncidentRecord,
  type RecommendationAIReviewResponse,
  type RecommendationArtifactView,
  type RecommendationArtifactViewKey,
  type RecommendationArtifactViewsPayload,
  type RecommendationDetailResponse,
  type RecommendationEvidenceRef,
  type RecommendationFeedbackAction,
  type RecommendationFeedbackListResponse,
  type RecommendationFeedbackRecord,
  type RecommendationFeedbackSaveResponse,
  type RecommendationRecord,
  type TaskArtifact,
} from '@/api/client'
import AIDiagnosisCard from '@/components/ai/AIDiagnosisCard'
import AIProviderStatusStrip from '@/components/ai/AIProviderStatusStrip'

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
  metadata?: TaskArtifact
}

interface ManifestMetadataDiff {
  filename: string
  added_lines: number
  removed_lines: number
  hunk_count: number
  total_changed_lines: number
  change_level: string
}

interface ManifestMetadataDocument {
  filename: string
  sha256: string
  line_count: number
  document_count: number
  resource_types: Array<{ kind: string; count: number }>
}

interface ManifestRiskSummary {
  level: string
  score: number
  review_required: boolean
  highlights: string[]
}

interface ManifestResourceHints {
  baseline_types: Array<{ kind: string; count: number }>
  recommended_types: Array<{ kind: string; count: number }>
  added_types: string[]
  removed_types: string[]
}

interface ManifestMetadata {
  schema_version: string
  generated_at: string
  baseline: ManifestMetadataDocument
  recommended: ManifestMetadataDocument
  diff: ManifestMetadataDiff
  risk_rules: string[]
  risk_summary: ManifestRiskSummary | null
  resource_hints: ManifestResourceHints | null
}

interface BundleArtifactContent {
  artifact: TaskArtifact
  filename: string
  content: string
}

interface FeedbackDraft {
  action: RecommendationFeedbackAction
  reasonCode: string
  comment: string
}

const feedbackActionLabel: Record<RecommendationFeedbackAction, string> = {
  adopt: '采纳',
  reject: '拒绝',
  rewrite: '改写',
}

const feedbackReasonOptions: Record<RecommendationFeedbackAction, Array<{ label: string; value: string }>> = {
  adopt: [
    { label: '证据充分', value: 'evidence_sufficient' },
    { label: '风险可控', value: 'risk_acceptable' },
    { label: '方案可执行', value: 'execution_ready' },
  ],
  reject: [
    { label: '证据不足', value: 'evidence_insufficient' },
    { label: '风险过高', value: 'risk_too_high' },
    { label: '场景不匹配', value: 'scenario_mismatch' },
  ],
  rewrite: [
    { label: '需要改写参数', value: 'tune_parameters' },
    { label: '需要补充回滚', value: 'missing_rollback' },
    { label: '需要分阶段执行', value: 'need_staged_rollout' },
  ],
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

const getChangeLevelColor = (changeLevel: string) => {
  if (changeLevel === 'high') {
    return 'red'
  }
  if (changeLevel === 'medium') {
    return 'orange'
  }
  return 'blue'
}

const getTaskStatusColor = (status: string) => {
  if (status === 'COMPLETED') {
    return 'green'
  }
  if (status === 'WAITING_CONFIRM') {
    return 'gold'
  }
  if (status === 'FAILED' || status === 'CANCELLED') {
    return 'red'
  }
  if (status === 'ANALYZING' || status === 'COLLECTING' || status === 'GENERATING') {
    return 'blue'
  }
  return 'default'
}

const getEvidenceSourceLabel = (sourceType: RecommendationEvidenceRef['source_type']) => {
  if (sourceType === 'artifact') {
    return '任务产物'
  }
  if (sourceType === 'log_snippet') {
    return '日志片段'
  }
  if (sourceType === 'metric_snapshot') {
    return '指标快照'
  }
  return '异常上下文'
}

const claimMeta: Record<string, { label: string; color: string }> = {
  summary: { label: '结论', color: 'blue' },
  cause: { label: '原因', color: 'purple' },
  action: { label: '动作', color: 'green' },
  risk: { label: '风险', color: 'orange' },
}

const getClaimMeta = (kind: string) => claimMeta[kind] || { label: '判断', color: 'default' }

const getArtifactViewLabel = (viewKey: RecommendationArtifactViewKey) => {
  if (viewKey === 'baseline') {
    return '基线'
  }
  if (viewKey === 'recommended') {
    return '建议'
  }
  return 'Diff'
}

const isProviderUnavailableError = (error: unknown) => {
  if (!(error instanceof Error)) {
    return false
  }
  return error.message.includes('LLM Provider') || error.message.includes('未启用可用的 LLM Provider')
}

const inferTimeRangeFromIncident = (incident: IncidentRecord) => {
  const startedAt = new Date(incident.time_window_start)
  const endedAt = new Date(incident.time_window_end)
  const durationMs = Math.max(0, endedAt.getTime() - startedAt.getTime())
  const hours = durationMs / (1000 * 60 * 60)
  if (hours > 6) {
    return '24h'
  }
  if (hours > 1) {
    return '6h'
  }
  return '1h'
}

const buildRecommendationAssistantPrompt = (
  incident: IncidentRecord,
  recommendation?: RecommendationRecord | null,
) => {
  if (recommendation) {
    return `请围绕 recommendation ${recommendation.recommendation_id} 复核风险、证据完整性和下一步只读验证动作。`
  }
  return `请基于 incident ${incident.incident_id} 的建议上下文，总结当前处理重点和下一步只读验证动作。`
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
    if (artifact.kind === 'json' && filename.includes('-manifest-meta') && !group.metadata) {
      group.metadata = artifact
      continue
    }
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
  const preferred = [group.recommended, group.baseline, group.diff, group.metadata].filter(Boolean) as TaskArtifact[]
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

const parseManifestMetadata = (content: string): ManifestMetadata | null => {
  // 兼容后端 metadata 渐进扩展，保证老产物也能继续展示。
  try {
    const parsed = JSON.parse(content) as Partial<ManifestMetadata>
    if (!parsed || typeof parsed !== 'object') {
      return null
    }
    if (!parsed.baseline || !parsed.recommended || !parsed.diff) {
      return null
    }
    return {
      schema_version: String(parsed.schema_version || 'v1'),
      generated_at: String(parsed.generated_at || ''),
      baseline: {
        filename: String(parsed.baseline.filename || ''),
        sha256: String(parsed.baseline.sha256 || ''),
        line_count: Number(parsed.baseline.line_count || 0),
        document_count: Number(parsed.baseline.document_count || 0),
        resource_types: Array.isArray((parsed.baseline as ManifestMetadataDocument).resource_types)
          ? (parsed.baseline as ManifestMetadataDocument).resource_types
            .map((item) => ({
              kind: String(item?.kind || '').trim(),
              count: Number(item?.count || 0),
            }))
            .filter((item) => Boolean(item.kind))
          : [],
      },
      recommended: {
        filename: String(parsed.recommended.filename || ''),
        sha256: String(parsed.recommended.sha256 || ''),
        line_count: Number(parsed.recommended.line_count || 0),
        document_count: Number(parsed.recommended.document_count || 0),
        resource_types: Array.isArray((parsed.recommended as ManifestMetadataDocument).resource_types)
          ? (parsed.recommended as ManifestMetadataDocument).resource_types
            .map((item) => ({
              kind: String(item?.kind || '').trim(),
              count: Number(item?.count || 0),
            }))
            .filter((item) => Boolean(item.kind))
          : [],
      },
      diff: {
        filename: String(parsed.diff.filename || ''),
        added_lines: Number(parsed.diff.added_lines || 0),
        removed_lines: Number(parsed.diff.removed_lines || 0),
        hunk_count: Number(parsed.diff.hunk_count || 0),
        total_changed_lines: Number((parsed.diff as ManifestMetadataDiff).total_changed_lines || (parsed.diff.added_lines || 0) + (parsed.diff.removed_lines || 0)),
        change_level: String((parsed.diff as ManifestMetadataDiff).change_level || 'low'),
      },
      risk_rules: Array.isArray(parsed.risk_rules) ? parsed.risk_rules.map((item) => String(item)).filter(Boolean) : [],
      risk_summary:
        parsed.risk_summary && typeof parsed.risk_summary === 'object'
          ? {
            level: String((parsed.risk_summary as ManifestRiskSummary).level || 'medium'),
            score: Number((parsed.risk_summary as ManifestRiskSummary).score || 0),
            review_required: Boolean((parsed.risk_summary as ManifestRiskSummary).review_required ?? true),
            highlights: Array.isArray((parsed.risk_summary as ManifestRiskSummary).highlights)
              ? (parsed.risk_summary as ManifestRiskSummary).highlights.map((item) => String(item)).filter(Boolean)
              : [],
          }
          : null,
      resource_hints:
        parsed.resource_hints && typeof parsed.resource_hints === 'object'
          ? {
            baseline_types: Array.isArray((parsed.resource_hints as ManifestResourceHints).baseline_types)
              ? (parsed.resource_hints as ManifestResourceHints).baseline_types
                .map((item) => ({
                  kind: String(item?.kind || '').trim(),
                  count: Number(item?.count || 0),
                }))
                .filter((item) => Boolean(item.kind))
              : [],
            recommended_types: Array.isArray((parsed.resource_hints as ManifestResourceHints).recommended_types)
              ? (parsed.resource_hints as ManifestResourceHints).recommended_types
                .map((item) => ({
                  kind: String(item?.kind || '').trim(),
                  count: Number(item?.count || 0),
                }))
                .filter((item) => Boolean(item.kind))
              : [],
            added_types: Array.isArray((parsed.resource_hints as ManifestResourceHints).added_types)
              ? (parsed.resource_hints as ManifestResourceHints).added_types.map((item) => String(item)).filter(Boolean)
              : [],
            removed_types: Array.isArray((parsed.resource_hints as ManifestResourceHints).removed_types)
              ? (parsed.resource_hints as ManifestResourceHints).removed_types.map((item) => String(item)).filter(Boolean)
              : [],
          }
          : null,
    }
  } catch {
    return null
  }
}

const shortHash = (value: string, size: number = 12) => {
  const text = String(value || '').trim()
  if (!text) {
    return '-'
  }
  return text.slice(0, size)
}

const buildEmptyFeedbackSummary = () => ({ adopt: 0, reject: 0, rewrite: 0 })

const getFeedbackActionColor = (action: RecommendationFeedbackAction) => {
  if (action === 'adopt') {
    return 'green'
  }
  if (action === 'reject') {
    return 'red'
  }
  return 'orange'
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
  const navigate = useNavigate()
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
  const [aiProviderReady, setAiProviderReady] = useState<boolean | null>(null)
  const [aiProviderChecking, setAiProviderChecking] = useState(true)
  const [assistantStatus, setAssistantStatus] = useState<AIAssistantStatusResponse | null>(null)
  const [aiReviewLoadingId, setAiReviewLoadingId] = useState('')
  const [aiReviewByRecommendationId, setAiReviewByRecommendationId] = useState<Record<string, RecommendationAIReviewResponse>>({})
  const [feedbackByRecommendationId, setFeedbackByRecommendationId] = useState<Record<string, RecommendationFeedbackListResponse>>({})
  const [feedbackLoadingId, setFeedbackLoadingId] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false)
  const [feedbackTarget, setFeedbackTarget] = useState<RecommendationRecord | null>(null)
  const [feedbackDraft, setFeedbackDraft] = useState<FeedbackDraft>({ action: 'adopt', reasonCode: '', comment: '' })
  const [evidenceDrawerOpen, setEvidenceDrawerOpen] = useState(false)
  const [evidenceLoadingId, setEvidenceLoadingId] = useState('')
  const [detailByRecommendationId, setDetailByRecommendationId] = useState<Record<string, RecommendationDetailResponse>>({})
  const [manifestMetaByRecommendationId, setManifestMetaByRecommendationId] = useState<Record<string, ManifestMetadata | null>>({})

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
  const activeRecommendationDetail = useMemo(
    () => (activeRecommendation ? detailByRecommendationId[activeRecommendation.recommendation_id] || null : null),
    [activeRecommendation, detailByRecommendationId],
  )
  const activeRecommendationClaims = useMemo<ClaimRecord[]>(
    () => activeRecommendationDetail?.claims || [],
    [activeRecommendationDetail],
  )
  const activeAiReviewClaims = useMemo<ClaimRecord[]>(
    () => activeAiReview?.claims || [],
    [activeAiReview],
  )
  const activeArtifactViews = useMemo<RecommendationArtifactViewsPayload | null>(
    () => activeRecommendationDetail?.artifact_views || null,
    [activeRecommendationDetail],
  )
  const activeTaskContext = useMemo(
    () => activeRecommendationDetail?.task_context || null,
    [activeRecommendationDetail],
  )
  const activeTaskTracePreview = useMemo(
    () => activeRecommendationDetail?.task_trace_preview || [],
    [activeRecommendationDetail],
  )
  const activeTaskTraceSummary = useMemo(
    () => activeRecommendationDetail?.task_trace_summary || null,
    [activeRecommendationDetail],
  )
  const activeManifestMeta = useMemo(
    () => (activeRecommendation ? manifestMetaByRecommendationId[activeRecommendation.recommendation_id] || null : null),
    [activeRecommendation, manifestMetaByRecommendationId],
  )
  const activeFeedbackPayload = useMemo(() => {
    if (!activeRecommendation) {
      return null
    }
    const detailFeedback = activeRecommendationDetail
    if (detailFeedback?.feedback_summary) {
      return {
        recommendation_id: activeRecommendation.recommendation_id,
        summary: detailFeedback.feedback_summary,
        items: detailFeedback.feedback_items || [],
      }
    }
    return feedbackByRecommendationId[activeRecommendation.recommendation_id] || {
      recommendation_id: activeRecommendation.recommendation_id,
      summary: buildEmptyFeedbackSummary(),
      items: [],
    }
  }, [activeRecommendation, activeRecommendationDetail, feedbackByRecommendationId])
  const isDiffPreview = preview?.artifact.kind === 'diff'
  const copyLabel = preview?.artifact.kind === 'manifest' ? '复制 YAML' : '复制内容'
  const diffSummary = useMemo(() => (isDiffPreview && preview ? buildDiffSummary(preview.content) : null), [isDiffPreview, preview])
  const activeArtifactMeta = useMemo<RecommendationArtifactView | null>(() => {
    if (!activeArtifactViews) {
      return null
    }
    if (activeArtifactView === 'baseline') {
      return activeArtifactViews.baseline || null
    }
    if (activeArtifactView === 'diff') {
      return activeArtifactViews.diff || null
    }
    return activeArtifactViews.recommended || null
  }, [activeArtifactView, activeArtifactViews])
  const manifestMetaDisplay = useMemo(() => {
    // 优先使用后端聚合字段，缺失时回退到本地 metadata 解析结果。
    if (activeArtifactViews?.baseline || activeArtifactViews?.recommended || activeArtifactViews?.diff) {
      return {
        schemaVersion: 'artifact_views',
        baseline: activeArtifactViews.baseline || null,
        recommended: activeArtifactViews.recommended || null,
        diff: activeArtifactViews.diff || null,
        riskRules: activeManifestMeta?.risk_rules || [],
        riskSummary: activeArtifactViews.risk_summary || activeManifestMeta?.risk_summary || null,
        resourceHints: activeArtifactViews.resource_hints || activeManifestMeta?.resource_hints || null,
        changeStats: activeArtifactViews.change_stats || null,
      }
    }
    if (!activeManifestMeta) {
      return null
    }
    return {
      schemaVersion: activeManifestMeta.schema_version,
      baseline: {
        filename: activeManifestMeta.baseline.filename,
        document_count: activeManifestMeta.baseline.document_count,
        line_count: activeManifestMeta.baseline.line_count,
        sha256: activeManifestMeta.baseline.sha256,
        resource_types: activeManifestMeta.baseline.resource_types || [],
      },
      recommended: {
        filename: activeManifestMeta.recommended.filename,
        document_count: activeManifestMeta.recommended.document_count,
        line_count: activeManifestMeta.recommended.line_count,
        sha256: activeManifestMeta.recommended.sha256,
        resource_types: activeManifestMeta.recommended.resource_types || [],
      },
      diff: {
        filename: activeManifestMeta.diff.filename,
        added_lines: activeManifestMeta.diff.added_lines,
        removed_lines: activeManifestMeta.diff.removed_lines,
        hunk_count: activeManifestMeta.diff.hunk_count,
        total_changed_lines: activeManifestMeta.diff.total_changed_lines,
        change_level: activeManifestMeta.diff.change_level,
      },
      riskRules: activeManifestMeta.risk_rules,
      riskSummary: activeManifestMeta.risk_summary,
      resourceHints: activeManifestMeta.resource_hints,
      changeStats: {
        total_changed_lines: activeManifestMeta.diff.total_changed_lines,
        change_level: activeManifestMeta.diff.change_level,
        added_lines: activeManifestMeta.diff.added_lines,
        removed_lines: activeManifestMeta.diff.removed_lines,
        hunk_count: activeManifestMeta.diff.hunk_count,
      },
    }
  }, [activeArtifactViews, activeManifestMeta])
  const resolvedDiffSummary = useMemo(() => {
    if (!isDiffPreview) {
      return null
    }
    const diffView = activeArtifactViews?.diff
    if (diffView) {
      return {
        fromFile: diffView.from_filename || '未识别基线文件',
        toFile: diffView.to_filename || '未识别建议文件',
        addedLines: diffView.added_lines || 0,
        removedLines: diffView.removed_lines || 0,
        hunkCount: diffView.hunk_count || 0,
      }
    }
    return diffSummary
  }, [activeArtifactViews, diffSummary, isDiffPreview])

  useEffect(() => {
    if (!selectedRecommendations.length) {
      if (activeRecommendationId) {
        setActiveRecommendationId('')
      }
      return
    }
    if (activeRecommendationId && selectedRecommendations.some((item) => item.recommendation_id === activeRecommendationId)) {
      return
    }
    setActiveRecommendationId(selectedRecommendations[0].recommendation_id)
  }, [selectedRecommendations, activeRecommendationId])

  const updateRouteState = (incidentId?: string, artifact?: TaskArtifact | null) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('incidentId')
    nextParams.delete('taskId')
    nextParams.delete('artifactId')
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
    void loadRecommendationDetail(recommendation.recommendation_id)
    void loadManifestMetadata(recommendation)
    void loadRecommendationFeedback(recommendation.recommendation_id)
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
    // 切换 incident 时同步清空页内派生缓存，避免上一条建议的视图残留到当前上下文。
    setSelected(detail)
    setAiReviewByRecommendationId({})
    setFeedbackByRecommendationId({})
    setDetailByRecommendationId({})
    setManifestMetaByRecommendationId({})
    return detail
  }

  const loadRecommendationDetail = async (recommendationId: string): Promise<RecommendationDetailResponse> => {
    const existing = detailByRecommendationId[recommendationId]
    if (existing) {
      return existing
    }
    setEvidenceLoadingId(recommendationId)
    try {
      const detail = (await recommendationsApi.get(recommendationId)) as RecommendationDetailResponse
      setDetailByRecommendationId((previous) => ({
        ...previous,
        [recommendationId]: detail,
      }))
      // 详情接口已经回传 feedback 聚合时，直接回灌到本地状态，避免页面二次请求造成闪动。
      if (detail.feedback_summary) {
        setFeedbackByRecommendationId((previous) => ({
          ...previous,
          [recommendationId]: {
            recommendation_id: recommendationId,
            summary: detail.feedback_summary || buildEmptyFeedbackSummary(),
            items: detail.feedback_items || [],
          },
        }))
      }
      return detail
    } finally {
      setEvidenceLoadingId('')
    }
  }

  const loadManifestMetadata = async (recommendation: RecommendationRecord) => {
    const recommendationId = recommendation.recommendation_id
    if (Object.prototype.hasOwnProperty.call(manifestMetaByRecommendationId, recommendationId)) {
      return manifestMetaByRecommendationId[recommendationId]
    }
    // metadata 只做增强展示，缺失时页面仍应保持可用。
    const metadataArtifact = buildArtifactGroup(recommendation.artifact_refs).metadata
    if (!metadataArtifact) {
      setManifestMetaByRecommendationId((previous) => ({ ...previous, [recommendationId]: null }))
      return null
    }
    try {
      const response = (await tasksApi.getArtifactContent(metadataArtifact.task_id, metadataArtifact.artifact_id)) as ArtifactContentResponse
      const parsed = parseManifestMetadata(response.content)
      setManifestMetaByRecommendationId((previous) => ({ ...previous, [recommendationId]: parsed }))
      return parsed
    } catch {
      setManifestMetaByRecommendationId((previous) => ({ ...previous, [recommendationId]: null }))
      return null
    }
  }

  const loadRecommendationFeedback = async (recommendationId: string, forceRefresh: boolean = false) => {
    if (!forceRefresh && feedbackByRecommendationId[recommendationId]) {
      return feedbackByRecommendationId[recommendationId]
    }
    setFeedbackLoadingId(recommendationId)
    try {
      const payload = (await recommendationsApi.listFeedback(recommendationId)) as RecommendationFeedbackListResponse
      setFeedbackByRecommendationId((previous) => ({
        ...previous,
        [recommendationId]: payload,
      }))
      return payload
    } catch (error) {
      message.error(error instanceof Error ? error.message : '反馈记录加载失败')
      return null
    } finally {
      setFeedbackLoadingId('')
    }
  }

  const openFeedbackModal = async (recommendation: RecommendationRecord, action: RecommendationFeedbackAction) => {
    setActiveRecommendationId(recommendation.recommendation_id)
    setFeedbackTarget(recommendation)
    const defaultReason = feedbackReasonOptions[action][0]?.value || ''
    setFeedbackDraft({
      action,
      reasonCode: defaultReason,
      comment: '',
    })
    setFeedbackModalOpen(true)
    void loadRecommendationFeedback(recommendation.recommendation_id)
  }

  const submitRecommendationFeedback = async () => {
    if (!feedbackTarget) {
      return
    }
    if ((feedbackDraft.action === 'reject' || feedbackDraft.action === 'rewrite') && !feedbackDraft.reasonCode.trim()) {
      message.warning('拒绝或改写反馈请先选择原因')
      return
    }

    setFeedbackSubmitting(true)
    try {
      const response = (await recommendationsApi.saveFeedback(feedbackTarget.recommendation_id, {
        action: feedbackDraft.action,
        reason_code: feedbackDraft.reasonCode,
        comment: feedbackDraft.comment,
        operator: 'ops_user',
      })) as RecommendationFeedbackSaveResponse

      setFeedbackByRecommendationId((previous) => {
        const existing = previous[feedbackTarget.recommendation_id]
        const nextItems: RecommendationFeedbackRecord[] = [
          response.item,
          ...(existing?.items || []).filter((item) => item.feedback_id !== response.item.feedback_id),
        ]
        return {
          ...previous,
          [feedbackTarget.recommendation_id]: {
            recommendation_id: feedbackTarget.recommendation_id,
            summary: response.summary,
            items: nextItems,
          },
        }
      })

      message.success(`反馈已提交：${feedbackActionLabel[feedbackDraft.action]}`)
      setFeedbackModalOpen(false)
      setFeedbackTarget(null)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '反馈提交失败')
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  const openEvidenceDrawer = async (recommendation: RecommendationRecord) => {
    setActiveRecommendationId(recommendation.recommendation_id)
    setEvidenceDrawerOpen(true)
    try {
      await loadRecommendationDetail(recommendation.recommendation_id)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证据加载失败')
    }
  }

  const jumpToTaskCenter = (taskId: string) => {
    const normalizedTaskId = taskId.trim()
    if (!normalizedTaskId) {
      return
    }
    navigate(`/tasks?taskId=${encodeURIComponent(normalizedTaskId)}`)
  }

  const jumpToEvidence = async (evidence: RecommendationEvidenceRef) => {
    const jump = evidence.jump
    if (!jump || jump.kind !== 'artifact' || !jump.task_id || !jump.artifact_id) {
      return
    }
    if (!selected || !activeRecommendation) {
      return
    }
    const owner = selectedRecommendations.find((item) =>
      item.artifact_refs.some((artifact) => artifact.artifact_id === jump.artifact_id && artifact.task_id === jump.task_id),
    )
    const targetArtifact = owner?.artifact_refs.find(
      (artifact) => artifact.artifact_id === jump.artifact_id && artifact.task_id === jump.task_id,
    )
    if (!owner || !targetArtifact) {
      message.warning('引用产物不存在或已失效')
      return
    }
    // 证据跳转复用主预览链路，这样路由、三视图和复制/下载状态都能保持一致。
    await previewArtifact(targetArtifact, owner.recommendation_id, selected.incident.incident_id)
    setEvidenceDrawerOpen(false)
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
    void loadRecommendationDetail(firstRecommendation.recommendation_id)
    void loadManifestMetadata(firstRecommendation)
    void loadRecommendationFeedback(firstRecommendation.recommendation_id)
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
      void loadRecommendationDetail(recommendation.recommendation_id)
      void loadManifestMetadata(recommendation)
      void loadRecommendationFeedback(recommendation.recommendation_id)
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
    // 建议生成是异步链路，短时间轮询即可把新草稿接回当前页，不额外引入复杂订阅。
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

  const refreshAIProviderAvailability = useCallback(async () => {
    setAiProviderChecking(true)
    try {
      const payload = (await aiApi.getAssistantStatus()) as AIAssistantStatusResponse
      setAssistantStatus(payload)
      setAiProviderReady(payload.provider_ready)
    } catch {
      // 状态接口失败时不阻塞主流程，但会隐藏更细的 AI 状态说明。
      setAssistantStatus(null)
      setAiProviderReady(true)
    } finally {
      setAiProviderChecking(false)
    }
  }, [])

  const openAssistantWorkbench = (recommendation?: RecommendationRecord | null) => {
    if (!selected) {
      return
    }
    // 把当前建议或异常上下文带入 AI 助手，确保后续对话围绕同一条处理链继续展开。
    const params = new URLSearchParams()
    const timeRange = inferTimeRangeFromIncident(selected.incident)
    params.set('source', recommendation ? 'recommendation' : 'incident')
    params.set('incidentId', selected.incident.incident_id)
    params.set('time_range', timeRange)
    params.set('prompt', buildRecommendationAssistantPrompt(selected.incident, recommendation))
    if (selected.incident.service_key) {
      params.set('service_key', selected.incident.service_key)
    }
    if (recommendation) {
      params.set('recommendationId', recommendation.recommendation_id)
    }
    navigate(`/assistant?${params.toString()}`)
  }

  const generate = async () => {
    if (!selected) {
      return
    }
    if (aiProviderReady === false) {
      message.warning('当前未配置可用 AI Provider，请先到 LLM 设置启用后再试')
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
    if (aiProviderReady === false) {
      message.warning('当前未配置可用 AI Provider，请先到 LLM 设置启用后再试')
      return
    }
    setAiReviewLoadingId(recommendation.recommendation_id)
    try {
      const response = (await recommendationsApi.aiReview(recommendation.recommendation_id)) as RecommendationAIReviewResponse
      setAiReviewByRecommendationId((previous) => ({
        ...previous,
        [recommendation.recommendation_id]: response,
      }))
      message.success('AI 复核已生成')
    } catch (error) {
      if (isProviderUnavailableError(error)) {
        setAiProviderReady(false)
        message.warning('AI Provider 不可用，请先到 LLM 设置完成配置')
        return
      }
      message.error(error instanceof Error ? error.message : 'AI 复核失败')
    } finally {
      setAiReviewLoadingId('')
    }
  }

  useEffect(() => {
    void loadData()
    void refreshAIProviderAvailability()
  }, [refreshAIProviderAvailability])

  const renderArtifactActions = (artifact: TaskArtifact, recommendation: RecommendationRecord) => (
    <Space wrap>
      <Button
        size="small"
        type={preview?.artifact.artifact_id === artifact.artifact_id ? 'primary' : 'default'}
        onClick={() => void openRecommendationWorkspace(recommendation, artifact)}
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

  const previewViewOptions = (
    activeArtifactViews?.available_views?.length
      ? activeArtifactViews.available_views.map((viewKey) => ({
          label: getArtifactViewLabel(viewKey),
          value: viewKey,
        }))
      : [
          previewArtifactGroup?.baseline ? { label: '基线', value: 'baseline' } : null,
          previewArtifactGroup?.recommended ? { label: '建议', value: 'recommended' } : null,
          previewArtifactGroup?.diff ? { label: 'Diff', value: 'diff' } : null,
        ].filter(Boolean)
  ) as Array<{ label: string; value: RecommendationArtifactViewKey }>

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
          <Button onClick={() => openAssistantWorkbench(activeRecommendation || null)} disabled={!selected}>
            AI 助手
          </Button>
          <Button
            type="primary"
            onClick={() => void generate()}
            loading={generating || aiProviderChecking}
            disabled={!selected || aiProviderReady === false || aiProviderChecking}
          >
            生成建议
          </Button>
          <Button onClick={() => void loadData()} loading={loading}>刷新详情</Button>
        </Space>
      </div>
      <AIProviderStatusStrip
        status={assistantStatus}
        loading={aiProviderChecking}
        onOpenSettings={() => navigate('/llm-settings')}
      />

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
                    const feedbackSummary = feedbackByRecommendationId[item.recommendation_id]?.summary || buildEmptyFeedbackSummary()
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
                            <div className="ops-action-groups">
                              <div className="ops-action-group">
                                <Text type="secondary" className="ops-action-group__label">基础</Text>
                                <Space wrap>
                                  <Button onClick={() => void openRecommendationWorkspace(item)} disabled={!item.artifact_refs.length}>
                                    打开页内工作区
                                  </Button>
                                  <Button
                                    onClick={() => void reviewRecommendationWithAi(item)}
                                    loading={aiReviewLoadingId === item.recommendation_id}
                                    disabled={aiProviderReady === false || aiProviderChecking}
                                  >
                                    AI 复核
                                  </Button>
                                  <Button
                                    onClick={() => void openEvidenceDrawer(item)}
                                    loading={evidenceLoadingId === item.recommendation_id}
                                  >
                                    证据引用
                                  </Button>
                                </Space>
                              </div>
                              <div className="ops-action-group">
                                <Text type="secondary" className="ops-action-group__label">反馈</Text>
                                <Space wrap>
                                  <Button
                                    size="small"
                                    onClick={() => void openFeedbackModal(item, 'adopt')}
                                    loading={feedbackSubmitting && feedbackTarget?.recommendation_id === item.recommendation_id && feedbackDraft.action === 'adopt'}
                                  >
                                    采纳
                                  </Button>
                                  <Button
                                    size="small"
                                    danger
                                    onClick={() => void openFeedbackModal(item, 'reject')}
                                    loading={feedbackSubmitting && feedbackTarget?.recommendation_id === item.recommendation_id && feedbackDraft.action === 'reject'}
                                  >
                                    拒绝
                                  </Button>
                                  <Button
                                    size="small"
                                    type="dashed"
                                    onClick={() => void openFeedbackModal(item, 'rewrite')}
                                    loading={feedbackSubmitting && feedbackTarget?.recommendation_id === item.recommendation_id && feedbackDraft.action === 'rewrite'}
                                  >
                                    改写
                                  </Button>
                                </Space>
                              </div>
                              <div className="ops-action-group">
                                <Text type="secondary" className="ops-action-group__label">导出</Text>
                                <Space wrap>
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
                              </div>
                            </div>
                            <Space size={6} wrap>
                              <Text type="secondary">共 {item.artifact_refs.length} 份产物</Text>
                              <Tag color="green">采纳 {feedbackSummary.adopt}</Tag>
                              <Tag color="red">拒绝 {feedbackSummary.reject}</Tag>
                              <Tag color="orange">改写 {feedbackSummary.rewrite}</Tag>
                            </Space>
                          </div>
                          <List
                            size="small"
                            dataSource={item.artifact_refs}
                            locale={{ emptyText: '暂无草稿产物' }}
                            renderItem={(artifact) => (
                              <List.Item>
                                <div className="ops-recommendation-artifact-row">
                                  <Space style={{ marginBottom: 6 }}>
                                    <Tag color={artifact.kind === 'diff' ? 'purple' : 'geekblue'}>{artifactLabelMap[artifact.kind] || artifact.kind}</Tag>
                                    <Text code>{getArtifactFilename(artifact)}</Text>
                                  </Space>
                                  <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{artifact.preview || '暂无预览摘要'}</Paragraph>
                                  <div className="ops-recommendation-artifact-row__actions">
                                    {renderArtifactActions(artifact, item)}
                                  </div>
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
                <div className="ops-recommendation-workspace__actions">
                  <div className="ops-action-groups ops-action-groups--compact">
                    <div className="ops-action-group">
                      <Text type="secondary" className="ops-action-group__label">基础</Text>
                      <Space wrap>
                        <Button onClick={() => void copyPreviewContent()} loading={previewCopying}>{copyLabel}</Button>
                        <Button
                          onClick={() => void reviewRecommendationWithAi(activeRecommendation)}
                          loading={aiReviewLoadingId === activeRecommendation.recommendation_id}
                          disabled={aiProviderReady === false || aiProviderChecking}
                        >
                          AI 复核
                        </Button>
                        <Button
                          onClick={() => void openEvidenceDrawer(activeRecommendation)}
                          loading={evidenceLoadingId === activeRecommendation.recommendation_id}
                        >
                          证据引用
                        </Button>
                      </Space>
                    </div>
                    <div className="ops-action-group">
                      <Text type="secondary" className="ops-action-group__label">反馈</Text>
                      <Space wrap>
                        <Button size="small" onClick={() => void openFeedbackModal(activeRecommendation, 'adopt')}>采纳</Button>
                        <Button size="small" danger onClick={() => void openFeedbackModal(activeRecommendation, 'reject')}>拒绝</Button>
                        <Button size="small" type="dashed" onClick={() => void openFeedbackModal(activeRecommendation, 'rewrite')}>改写</Button>
                      </Space>
                    </div>
                    <div className="ops-action-group">
                      <Text type="secondary" className="ops-action-group__label">导出</Text>
                      <Space wrap>
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
                    </div>
                  </div>
                </div>
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
                      <Text code>{activeArtifactMeta?.filename || preview.filename}</Text>
                      <Text type="secondary">
                        当前视图：{activeArtifactMeta?.label || getArtifactViewLabel(activeArtifactView)}
                      </Text>
                      {activeArtifactMeta?.summary ? <Text type="secondary">{activeArtifactMeta.summary}</Text> : null}
                    </div>
                  </div>

                  {previewViewOptions.length > 1 ? (
                    <Segmented block options={previewViewOptions} value={activeArtifactView} onChange={(value) => void switchPreviewView(String(value))} />
                  ) : null}

                  {manifestMetaDisplay ? (
                    <Card type="inner" title="草稿元数据" size="small">
                      <Space wrap style={{ marginBottom: 10 }}>
                        <Tag color="geekblue">Schema：{manifestMetaDisplay.schemaVersion}</Tag>
                        <Tag color="blue">
                          Diff +{manifestMetaDisplay.diff?.added_lines || 0} / -{manifestMetaDisplay.diff?.removed_lines || 0}
                        </Tag>
                        <Tag color="purple">变更块 {manifestMetaDisplay.diff?.hunk_count || 0}</Tag>
                      </Space>
                      <div className="ops-manifest-meta-grid">
                        <div className="ops-manifest-meta-card">
                          <Text strong>基线</Text>
                          <Text code>{manifestMetaDisplay.baseline?.filename || '-'}</Text>
                          <Text type="secondary">
                            文档 {manifestMetaDisplay.baseline?.document_count || 0} · 行数 {manifestMetaDisplay.baseline?.line_count || 0}
                          </Text>
                          <Text type="secondary">SHA {shortHash(manifestMetaDisplay.baseline?.sha256 || '')}</Text>
                        </div>
                        <div className="ops-manifest-meta-card">
                          <Text strong>建议</Text>
                          <Text code>{manifestMetaDisplay.recommended?.filename || '-'}</Text>
                          <Text type="secondary">
                            文档 {manifestMetaDisplay.recommended?.document_count || 0} · 行数 {manifestMetaDisplay.recommended?.line_count || 0}
                          </Text>
                          <Text type="secondary">SHA {shortHash(manifestMetaDisplay.recommended?.sha256 || '')}</Text>
                        </div>
                      </div>
                      <Space wrap style={{ marginTop: 10 }}>
                        <Tag color={getChangeLevelColor(manifestMetaDisplay.changeStats?.change_level || manifestMetaDisplay.diff?.change_level || 'low')}>
                          变更强度：{manifestMetaDisplay.changeStats?.change_level || manifestMetaDisplay.diff?.change_level || 'low'}
                        </Tag>
                        <Tag>
                          变更总行数：{manifestMetaDisplay.changeStats?.total_changed_lines || manifestMetaDisplay.diff?.total_changed_lines || 0}
                        </Tag>
                        {manifestMetaDisplay.riskSummary ? (
                          <Tag color={getRiskLevelColor(manifestMetaDisplay.riskSummary.level)}>
                            风险等级：{manifestMetaDisplay.riskSummary.level}
                          </Tag>
                        ) : null}
                      </Space>
                      {Array.isArray(manifestMetaDisplay.baseline?.resource_types) && manifestMetaDisplay.baseline.resource_types.length > 0 ? (
                        <Space wrap style={{ marginTop: 8 }}>
                          <Text type="secondary">基线对象：</Text>
                          {manifestMetaDisplay.baseline.resource_types.map((item: { kind: string; count: number }) => (
                            <Tag key={`baseline-kind-${item.kind}`} color="blue">{item.kind} x{item.count}</Tag>
                          ))}
                        </Space>
                      ) : null}
                      {Array.isArray(manifestMetaDisplay.recommended?.resource_types) && manifestMetaDisplay.recommended.resource_types.length > 0 ? (
                        <Space wrap style={{ marginTop: 8 }}>
                          <Text type="secondary">建议对象：</Text>
                          {manifestMetaDisplay.recommended.resource_types.map((item: { kind: string; count: number }) => (
                            <Tag key={`recommended-kind-${item.kind}`} color="geekblue">{item.kind} x{item.count}</Tag>
                          ))}
                        </Space>
                      ) : null}
                      {manifestMetaDisplay.resourceHints?.added_types?.length ? (
                        <Space wrap style={{ marginTop: 8 }}>
                          <Text type="secondary">新增对象：</Text>
                          {manifestMetaDisplay.resourceHints.added_types.map((kind) => (
                            <Tag key={`added-kind-${kind}`} color="green">{kind}</Tag>
                          ))}
                        </Space>
                      ) : null}
                      {manifestMetaDisplay.resourceHints?.removed_types?.length ? (
                        <Space wrap style={{ marginTop: 8 }}>
                          <Text type="secondary">移除对象：</Text>
                          {manifestMetaDisplay.resourceHints.removed_types.map((kind) => (
                            <Tag key={`removed-kind-${kind}`} color="red">{kind}</Tag>
                          ))}
                        </Space>
                      ) : null}
                      {manifestMetaDisplay.riskSummary?.highlights?.length ? (
                        <List
                          size="small"
                          style={{ marginTop: 10 }}
                          dataSource={manifestMetaDisplay.riskSummary.highlights}
                          renderItem={(item) => <List.Item>{item}</List.Item>}
                        />
                      ) : null}
                      {manifestMetaDisplay.riskRules.length > 0 ? (
                        <Space wrap style={{ marginTop: 10 }}>
                          {manifestMetaDisplay.riskRules.map((rule) => (
                            <Tag key={rule}>{rule}</Tag>
                          ))}
                        </Space>
                      ) : null}
                    </Card>
                  ) : null}

                  {activeTaskContext ? (
                    <Card type="inner" title="任务追踪" size="small">
                      <Space wrap style={{ marginBottom: 10 }}>
                        <Tag color={getTaskStatusColor(activeTaskContext.status)}>
                          任务状态：{activeTaskContext.status}
                        </Tag>
                        <Tag>阶段：{activeTaskContext.current_stage}</Tag>
                        <Tag color="blue">进度：{activeTaskContext.progress}%</Tag>
                        {activeTaskContext.completed_at ? (
                          <Tag color="green">
                            完成时间：{new Date(activeTaskContext.completed_at).toLocaleString('zh-CN', { hour12: false })}
                          </Tag>
                        ) : null}
                      </Space>
                      <Paragraph style={{ marginBottom: 8 }}>
                        <Text strong>当前说明：</Text>
                        {activeTaskContext.progress_message || '-'}
                      </Paragraph>
                      {activeTaskContext.approval ? (
                        <Alert
                          type="success"
                          showIcon
                          style={{ marginBottom: 10 }}
                          message={`审批通过：${activeTaskContext.approval.approved_by}`}
                          description={activeTaskContext.approval.approval_note || '未填写审批备注'}
                        />
                      ) : (
                        <Alert
                          type="info"
                          showIcon
                          style={{ marginBottom: 10 }}
                          message="审批状态：未确认"
                          description="当前建议尚未被人工审批。"
                        />
                      )}
                      <Space style={{ marginBottom: 8 }}>
                        <Button size="small" onClick={() => jumpToTaskCenter(activeTaskContext.task_id)}>
                          打开任务中心
                        </Button>
                        <Text type="secondary">
                          Trace 步骤：{activeTaskTraceSummary?.total_steps || activeTaskTracePreview.length}
                        </Text>
                      </Space>
                      <List
                        size="small"
                        dataSource={activeTaskTracePreview.slice(-6).reverse()}
                        locale={{ emptyText: '暂无 Trace 记录' }}
                        renderItem={(item) => {
                          const observation = (item.observation as Record<string, unknown> | undefined) || {}
                          return (
                            <List.Item>
                              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                                <Space wrap size={8}>
                                  <Tag color="blue">{String(item.stage || '-')}</Tag>
                                  <Text code>{String(item.step || '-')}</Text>
                                  <Text type="secondary">{String(item.action || '-')}</Text>
                                  <Text type="secondary">
                                    {item.created_at ? new Date(String(item.created_at)).toLocaleString('zh-CN', { hour12: false }) : '-'}
                                  </Text>
                                </Space>
                                <Paragraph style={{ marginBottom: 0 }}>
                                  {String(observation.summary || '-')}
                                </Paragraph>
                              </Space>
                            </List.Item>
                          )
                        }}
                      />
                    </Card>
                  ) : null}

                  {activeFeedbackPayload ? (
                    <Card type="inner" title="反馈闭环" size="small" loading={Boolean(activeRecommendation) && feedbackLoadingId === activeRecommendation?.recommendation_id}>
                      <Space wrap style={{ marginBottom: 10 }}>
                        <Tag color="green">采纳 {activeFeedbackPayload.summary.adopt}</Tag>
                        <Tag color="red">拒绝 {activeFeedbackPayload.summary.reject}</Tag>
                        <Tag color="orange">改写 {activeFeedbackPayload.summary.rewrite}</Tag>
                      </Space>
                      <List
                        size="small"
                        dataSource={activeFeedbackPayload.items.slice(0, 5)}
                        locale={{ emptyText: '还没有反馈记录' }}
                        renderItem={(item) => (
                          <List.Item>
                            <Space size={8} wrap>
                              <Tag color={getFeedbackActionColor(item.action)}>{feedbackActionLabel[item.action]}</Tag>
                              <Text code>{item.reason_code || '-'}</Text>
                              <Text type="secondary">{item.operator}</Text>
                              <Text type="secondary">{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</Text>
                            </Space>
                            {item.comment ? (
                              <Paragraph style={{ marginBottom: 0, marginTop: 6 }}>{item.comment}</Paragraph>
                            ) : null}
                          </List.Item>
                        )}
                      />
                    </Card>
                  ) : null}

                  {activeRecommendationClaims.length ? (
                    <Card type="inner" title="结论拆解" size="small">
                      <List
                        size="small"
                        dataSource={activeRecommendationClaims}
                        renderItem={(item) => {
                          const meta = getClaimMeta(item.kind)
                          return (
                            <List.Item>
                              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                                <Space wrap>
                                  <Tag color={meta.color}>{meta.label}</Tag>
                                  {item.title ? <Text strong>{item.title}</Text> : null}
                                  <Tag color="blue">置信度 {Math.round((item.confidence || 0) * 100)}%</Tag>
                                  <Tag>证据 {item.evidence_ids.length}</Tag>
                                </Space>
                                <Paragraph style={{ marginBottom: 0 }}>{item.statement}</Paragraph>
                                {item.limitations.length ? (
                                  <Text type="secondary">限制：{item.limitations.join('；')}</Text>
                                ) : null}
                              </Space>
                            </List.Item>
                          )
                        }}
                      />
                    </Card>
                  ) : null}

                  {activeAiReview ? (
                    <Card type="inner" title="AI 复核" size="small">
                      <AIDiagnosisCard
                        summary={activeAiReview.summary}
                        riskLevel={activeAiReview.risk_level}
                        confidence={activeAiReview.confidence}
                        provider={activeAiReview.provider}
                        parseMode={activeAiReview.parse_mode}
                        supportingText={activeAiReview.risk_assessment}
                        validationChecks={activeAiReview.validation_checks}
                        rollbackPlan={activeAiReview.rollback_plan}
                        evidenceCitations={activeAiReview.evidence_citations}
                        roleViews={activeAiReview.role_views}
                      />
                      {activeAiReviewClaims.length ? (
                        <List
                          size="small"
                          header={<Text strong>AI 复核拆解</Text>}
                          dataSource={activeAiReviewClaims}
                          style={{ marginTop: 12 }}
                          renderItem={(item) => {
                            const meta = getClaimMeta(item.kind)
                            return (
                              <List.Item>
                                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                                  <Space wrap>
                                    <Tag color={meta.color}>{meta.label}</Tag>
                                    {item.title ? <Text strong>{item.title}</Text> : null}
                                    <Tag color="blue">置信度 {Math.round((item.confidence || 0) * 100)}%</Tag>
                                    <Tag>证据 {item.evidence_ids.length}</Tag>
                                  </Space>
                                  <Paragraph style={{ marginBottom: 0 }}>{item.statement}</Paragraph>
                                  {item.limitations.length ? (
                                    <Text type="secondary">限制：{item.limitations.join('；')}</Text>
                                  ) : null}
                                </Space>
                              </List.Item>
                            )
                          }}
                        />
                      ) : null}
                    </Card>
                  ) : null}

                  {isDiffPreview && resolvedDiffSummary ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      <div className="ops-diff-summary">
                        <div className="ops-diff-summary__files">
                          <div className="ops-diff-summary__file-card">
                            <span className="ops-diff-summary__label">基线文件</span>
                            <Text code>{resolvedDiffSummary.fromFile}</Text>
                          </div>
                          <div className="ops-diff-summary__file-card">
                            <span className="ops-diff-summary__label">建议文件</span>
                            <Text code>{resolvedDiffSummary.toFile}</Text>
                          </div>
                        </div>
                        <Space wrap>
                          <Tag color="green">新增 {resolvedDiffSummary.addedLines} 行</Tag>
                          <Tag color="red">删除 {resolvedDiffSummary.removedLines} 行</Tag>
                          <Tag color="blue">变更块 {resolvedDiffSummary.hunkCount} 处</Tag>
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

      <Modal
        title={feedbackTarget ? `提交反馈 · ${feedbackActionLabel[feedbackDraft.action]}` : '提交反馈'}
        open={feedbackModalOpen}
        onCancel={() => {
          setFeedbackModalOpen(false)
          setFeedbackTarget(null)
        }}
        onOk={() => void submitRecommendationFeedback()}
        confirmLoading={feedbackSubmitting}
        okText="提交反馈"
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div>
            <Text type="secondary">反馈动作</Text>
            <Segmented
              block
              value={feedbackDraft.action}
              options={[
                { label: '采纳', value: 'adopt' },
                { label: '拒绝', value: 'reject' },
                { label: '改写', value: 'rewrite' },
              ]}
              onChange={(value) => {
                const nextAction = String(value) as RecommendationFeedbackAction
                const defaultReason = feedbackReasonOptions[nextAction][0]?.value || ''
                setFeedbackDraft((previous) => ({
                  ...previous,
                  action: nextAction,
                  reasonCode: defaultReason,
                }))
              }}
            />
          </div>
          <div>
            <Text type="secondary">原因代码</Text>
            <Select
              style={{ width: '100%' }}
              value={feedbackDraft.reasonCode}
              options={feedbackReasonOptions[feedbackDraft.action]}
              onChange={(value) => setFeedbackDraft((previous) => ({ ...previous, reasonCode: String(value) }))}
              placeholder="选择反馈原因"
            />
          </div>
          <div>
            <Text type="secondary">补充说明</Text>
            <Input.TextArea
              value={feedbackDraft.comment}
              rows={4}
              maxLength={500}
              placeholder="可选，补充具体理由与建议"
              onChange={(event) => setFeedbackDraft((previous) => ({ ...previous, comment: event.target.value }))}
            />
          </div>
        </Space>
      </Modal>

      <Drawer
        title="证据引用"
        open={evidenceDrawerOpen}
        width={560}
        onClose={() => setEvidenceDrawerOpen(false)}
        destroyOnClose={false}
      >
        {!activeRecommendation ? (
          <Empty description="请选择建议后查看证据引用" />
        ) : !activeRecommendationDetail ? (
          <Empty description={evidenceLoadingId === activeRecommendation.recommendation_id ? '正在加载证据...' : '暂无证据详情'} />
        ) : (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Alert
              type={activeRecommendationDetail.evidence_status === 'sufficient' ? 'success' : 'warning'}
              showIcon
              message={activeRecommendationDetail.evidence_status === 'sufficient' ? '证据链可追溯' : '证据不足'}
              description={activeRecommendationDetail.evidence_message}
            />
            <Space wrap>
              <Tag color={activeRecommendationDetail.evidence_status === 'sufficient' ? 'green' : 'orange'}>
                状态：{activeRecommendationDetail.evidence_status === 'sufficient' ? '可追溯' : '证据不足'}
              </Tag>
              <Tag color="blue">有效置信度：{Math.round(activeRecommendationDetail.confidence_effective * 100)}%</Tag>
              <Tag>证据总数：{activeRecommendationDetail.evidence_summary.total}</Tag>
              {activeRecommendationDetail.evidence_summary.incident_evidence ? (
                <Tag color="gold">上下文证据：{activeRecommendationDetail.evidence_summary.incident_evidence}</Tag>
              ) : null}
            </Space>
            <Paragraph style={{ marginBottom: 0 }}>
              <Text strong>建议结论：</Text>
              {activeRecommendationDetail.recommendation_effective}
            </Paragraph>
            <div>
              <Text strong style={{ display: 'block', marginBottom: 8 }}>现场日志样本</Text>
              <List
                size="small"
                dataSource={activeRecommendationDetail.log_samples}
                locale={{ emptyText: '暂无现场日志样本' }}
                renderItem={(item) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space wrap style={{ marginBottom: 6 }}>
                        <Tag color={item.status >= 500 ? 'red' : item.status >= 400 ? 'orange' : 'blue'}>{item.status}</Tag>
                        <Tag>{item.method}</Tag>
                        <Text code>{item.path}</Text>
                        <Tag color="geekblue">{item.latency_ms} ms</Tag>
                      </Space>
                      <Paragraph style={{ marginBottom: 4 }}>
                        {item.timestamp} · {item.client_ip} · {item.geo_label}
                      </Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {item.browser} / {item.os} / {item.device} · {item.user_agent}
                      </Paragraph>
                    </div>
                  </List.Item>
                )}
              />
            </div>
            <List
              size="small"
              dataSource={activeRecommendationDetail.evidence_refs}
              locale={{ emptyText: '暂无可展示证据' }}
              renderItem={(item) => (
                <List.Item
                  actions={
                    item.jump?.kind === 'artifact' && item.jump.artifact_id && item.jump.task_id
                      ? [
                          <Button key={`jump-${item.evidence_id}`} size="small" onClick={() => void jumpToEvidence(item)}>
                            跳转产物
                          </Button>,
                        ]
                      : []
                  }
                >
                  <div style={{ width: '100%' }}>
                    <Space wrap style={{ marginBottom: 6 }}>
                      <Tag color="geekblue">{getEvidenceSourceLabel(item.source_type)}</Tag>
                      <Text strong>{item.title}</Text>
                      {item.metric ? <Text code>{item.metric}</Text> : null}
                    </Space>
                    <Paragraph style={{ marginBottom: 4 }}>{item.summary}</Paragraph>
                    {item.quote ? (
                      <Paragraph type="secondary" style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                        {item.quote}
                      </Paragraph>
                    ) : null}
                  </div>
                </List.Item>
              )}
            />
          </Space>
        )}
      </Drawer>
    </div>
  )
}

export default RecommendationCenter
