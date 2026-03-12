import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  List,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  tasksApi,
  type ArtifactContentResponse,
  type TaskArtifact,
  type TaskArtifactGroup,
  type TaskArtifactListResponse,
  type TaskDetailResponse,
  type TaskFailureDiagnosis,
  type TaskRecord,
} from '@/api/client'
import { useTaskEventStream } from '@/hooks/useTaskEventStream'

const { Paragraph, Text, Title } = Typography
const { TextArea } = Input

interface TaskListResponse {
  items: TaskRecord[]
  total: number
}

interface PreviewState {
  artifact: TaskArtifact
  content: string
  filename: string
}

const emptyArtifactGroups: TaskArtifactGroup[] = []

const artifactLabelMap: Record<string, string> = {
  manifest: 'YAML 草稿',
  diff: '变更差异',
  report: '报告文件',
  json: 'JSON 结果',
  text: '文本内容',
}

export const TaskCenter: React.FC = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [tasks, setTasks] = useState<TaskRecord[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskDetailResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewArtifactId, setPreviewArtifactId] = useState('')
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [artifactKindFilter, setArtifactKindFilter] = useState('all')
  const [artifactQueryInput, setArtifactQueryInput] = useState('')
  const [artifactQuery, setArtifactQuery] = useState('')
  const [artifactItems, setArtifactItems] = useState<TaskArtifact[]>([])
  const [artifactGroups, setArtifactGroups] = useState<TaskArtifactGroup[]>(emptyArtifactGroups)
  const [artifactTotal, setArtifactTotal] = useState(0)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)
  const [approveModalOpen, setApproveModalOpen] = useState(false)
  const [approveSubmitting, setApproveSubmitting] = useState(false)
  const [approvedBy, setApprovedBy] = useState('operator')
  const [approvalNote, setApprovalNote] = useState('')
  const previousTaskIdRef = useRef<string | undefined>(undefined)

  const selectedTaskId = selectedTask?.task.task_id
  const failureDiagnosis = selectedTask?.failure_diagnosis || null
  const recommendationArtifact = useMemo(
    () => selectedTask?.artifacts.find((artifact) => artifact.kind === 'diff') || selectedTask?.artifacts.find((artifact) => artifact.kind === 'manifest') || null,
    [selectedTask],
  )
  const artifactKindOptions = useMemo(() => {
    const kinds = new Set((selectedTask?.artifacts || []).map((artifact) => artifact.kind))
    return [
      { label: '全部类型', value: 'all' },
      ...Array.from(kinds)
        .sort((left, right) => left.localeCompare(right, 'zh-CN'))
        .map((kind) => ({ label: artifactLabelMap[kind] || kind, value: kind })),
    ]
  }, [selectedTask])
  const groupedArtifacts = artifactGroups.length
    ? artifactGroups
    : [{ group_key: 'all', count: artifactItems.length, items: artifactItems }]

  const loadTaskDetail = useCallback(async (taskId: string) => {
    const detail = (await tasksApi.get(taskId)) as TaskDetailResponse
    setSelectedTask(detail)
    return detail
  }, [])

  // 任务详情与产物检索分离加载，保证筛选变更时无需重拉整页详情。
  const loadArtifacts = useCallback(async (taskId: string) => {
    setArtifactLoading(true)
    try {
      const response = (await tasksApi.listArtifacts(taskId, {
        kind: artifactKindFilter === 'all' ? undefined : artifactKindFilter,
        query: artifactQuery || undefined,
        group_by: 'kind',
      })) as TaskArtifactListResponse
      setArtifactItems(response.items)
      setArtifactGroups(response.groups)
      setArtifactTotal(response.total)
    } finally {
      setArtifactLoading(false)
    }
  }, [artifactKindFilter, artifactQuery])

  const loadTasks = useCallback(async () => {
    setLoading(true)
    try {
      const response = (await tasksApi.list()) as TaskListResponse
      setTasks(response.items)
      const preferredTaskId = selectedTaskId && response.items.some((item) => item.task_id === selectedTaskId)
        ? selectedTaskId
        : response.items[0]?.task_id
      if (preferredTaskId) {
        await loadTaskDetail(preferredTaskId)
      } else {
        setSelectedTask(null)
      }
    } finally {
      setLoading(false)
    }
  }, [loadTaskDetail, selectedTaskId])

  useTaskEventStream({
    enabled: true,
    onEvent: (event) => {
      if (event.task_id) {
        void loadTasks()
      }
    },
  })

  useEffect(() => {
    void loadTasks()
  }, [loadTasks])

  useEffect(() => {
    const taskChanged = previousTaskIdRef.current !== selectedTaskId
    previousTaskIdRef.current = selectedTaskId

    if (taskChanged) {
      setArtifactItems([])
      setArtifactGroups(emptyArtifactGroups)
      setArtifactTotal(0)
    }

    if (!selectedTaskId) {
      return
    }
    void loadArtifacts(selectedTaskId)
  }, [selectedTaskId, loadArtifacts])

  const approveSelectedTask = async () => {
    if (!selectedTask) {
      return
    }
    setApproveSubmitting(true)
    try {
      await tasksApi.approve(selectedTask.task.task_id, {
        approved_by: approvedBy,
        approval_note: approvalNote,
      })
      message.success('任务已确认')
      setApproveModalOpen(false)
      setApprovalNote('')
      await loadTaskDetail(selectedTask.task.task_id)
      await loadTasks()
    } finally {
      setApproveSubmitting(false)
    }
  }

  const cancelSelectedTask = async () => {
    if (!selectedTask) {
      return
    }
    await tasksApi.cancel(selectedTask.task.task_id)
    message.success('任务已取消')
    await loadTaskDetail(selectedTask.task.task_id)
    await loadTasks()
  }

  // 失败诊断支持单独刷新，避免整页重载时丢失当前阅读上下文。
  const refreshFailureDiagnosis = async () => {
    if (!selectedTask) {
      return
    }
    if (!['FAILED', 'CANCELLED'].includes(selectedTask.task.status)) {
      return
    }

    setDiagnosisLoading(true)
    try {
      const diagnosis = (await tasksApi.getDiagnosis(selectedTask.task.task_id)) as TaskFailureDiagnosis
      setSelectedTask((prev) => {
        if (!prev || prev.task.task_id !== selectedTask.task.task_id) {
          return prev
        }
        return {
          ...prev,
          failure_diagnosis: diagnosis,
        }
      })
      message.success('失败诊断已刷新')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '失败诊断刷新失败')
    } finally {
      setDiagnosisLoading(false)
    }
  }

  const applyArtifactSearch = () => {
    setArtifactQuery(artifactQueryInput.trim())
  }

  const resetArtifactSearch = () => {
    setArtifactKindFilter('all')
    setArtifactQueryInput('')
    setArtifactQuery('')
  }

  const previewArtifact = async (artifact: TaskArtifact) => {
    setPreviewLoading(true)
    setPreviewArtifactId(artifact.artifact_id)
    try {
      const response = (await tasksApi.getArtifactContent(artifact.task_id, artifact.artifact_id)) as ArtifactContentResponse
      setPreview({ artifact, content: response.content, filename: response.filename })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '读取产物失败')
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

  const openRecommendationDraft = () => {
    if (!selectedTask) {
      return
    }
    const payloadIncidentValue = selectedTask.task.payload['incident_id']
    const resultIncidentValue = selectedTask.task.result_ref?.['incident_id']
    const payloadIncidentId = typeof payloadIncidentValue === 'string' ? payloadIncidentValue : ''
    const resultIncidentId = typeof resultIncidentValue === 'string' ? resultIncidentValue : ''
    const incidentId = payloadIncidentId || resultIncidentId
    const params = new URLSearchParams()
    if (incidentId) {
      params.set('incidentId', incidentId)
    }
    if (recommendationArtifact) {
      params.set('taskId', recommendationArtifact.task_id)
      params.set('artifactId', recommendationArtifact.artifact_id)
    }
    navigate(`/recommendations${params.toString() ? `?${params.toString()}` : ''}`)
  }

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>任务中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            跟踪分析、报表和建议任务的状态流、证据片段和产物输出，并支持直接跳转到建议草稿视图。
          </Paragraph>
        </div>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card title="任务列表" loading={loading} className="ops-surface-card">
            <Table
              rowKey="task_id"
              pagination={false}
              dataSource={tasks}
              onRow={(record) => ({
                onClick: () => void loadTaskDetail(record.task_id),
                style: { cursor: 'pointer' },
              })}
              columns={[
                { title: '任务类型', dataIndex: 'task_type' },
                {
                  title: '状态',
                  dataIndex: 'status',
                  render: (value: string) => <Tag color={value === 'COMPLETED' ? 'green' : value === 'FAILED' ? 'red' : value === 'WAITING_CONFIRM' ? 'gold' : 'blue'}>{value}</Tag>,
                },
                { title: '进度', dataIndex: 'progress', width: 100, render: (value: number) => `${value}%` },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card
            title="任务详情"
            loading={loading}
            className="ops-surface-card"
            extra={
              <Space>
                <Button onClick={() => setApproveModalOpen(true)} disabled={selectedTask?.task.status !== 'WAITING_CONFIRM'}>确认</Button>
                <Button onClick={() => void refreshFailureDiagnosis()} loading={diagnosisLoading} disabled={!selectedTask || !['FAILED', 'CANCELLED'].includes(selectedTask.task.status)}>
                  失败诊断
                </Button>
                <Button onClick={openRecommendationDraft} disabled={!selectedTask || selectedTask.task.task_type !== 'recommendation_generation' || !recommendationArtifact}>
                  查看建议草稿
                </Button>
                <Button danger onClick={() => void cancelSelectedTask()} disabled={!selectedTask}>取消</Button>
              </Space>
            }
          >
            {!selectedTask ? (
              <Empty description="请选择一个任务" />
            ) : (
              <div>
                <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
                  <Descriptions.Item label="任务 ID">{selectedTask.task.task_id}</Descriptions.Item>
                  <Descriptions.Item label="状态">{selectedTask.task.status}</Descriptions.Item>
                  <Descriptions.Item label="当前阶段">{selectedTask.task.current_stage}</Descriptions.Item>
                  <Descriptions.Item label="进度消息">{selectedTask.task.progress_message || '-'}</Descriptions.Item>
                  <Descriptions.Item label="确认人">{selectedTask.task.approval?.approved_by || '-'}</Descriptions.Item>
                  <Descriptions.Item label="确认时间">{selectedTask.task.approval?.approved_at || '-'}</Descriptions.Item>
                </Descriptions>
                {selectedTask.task.approval?.approval_note ? (
                  <Card type="inner" title="确认备注" style={{ marginBottom: 16 }}>
                    <Paragraph style={{ marginBottom: 0 }}>{selectedTask.task.approval.approval_note}</Paragraph>
                  </Card>
                ) : null}
                {selectedTask.task.error ? (
                  <Card type="inner" title="失败信息" style={{ marginBottom: 16 }}>
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="错误码">{selectedTask.task.error.error_code}</Descriptions.Item>
                      <Descriptions.Item label="失败阶段">{selectedTask.task.error.failed_stage || '-'}</Descriptions.Item>
                      <Descriptions.Item label="错误消息">
                        <Paragraph style={{ marginBottom: 0 }}>{selectedTask.task.error.error_message}</Paragraph>
                      </Descriptions.Item>
                    </Descriptions>
                  </Card>
                ) : null}
                {failureDiagnosis ? (
                  <Card type="inner" title="失败诊断" style={{ marginBottom: 16 }}>
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      <Space wrap>
                        <Tag color={failureDiagnosis.retryable ? 'blue' : 'red'}>
                          {failureDiagnosis.retryable ? '可重试' : '需先修复配置'}
                        </Tag>
                        <Tag>Trace 步骤 {failureDiagnosis.trace_stats.total_steps}</Tag>
                        <Tag>产物 {failureDiagnosis.artifact_count}</Tag>
                      </Space>
                      <Descriptions column={1} size="small">
                        <Descriptions.Item label="最后一步">
                          {failureDiagnosis.trace_stats.last_step
                            ? `${failureDiagnosis.trace_stats.last_step.step} / ${failureDiagnosis.trace_stats.last_step.action} (${failureDiagnosis.trace_stats.last_step.stage})`
                            : '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="最后观察">
                          {failureDiagnosis.trace_stats.last_step?.summary || '-'}
                        </Descriptions.Item>
                      </Descriptions>

                      <div>
                        <Text strong>可能原因</Text>
                        <List
                          size="small"
                          dataSource={failureDiagnosis.possible_causes}
                          renderItem={(item) => <List.Item>{item}</List.Item>}
                        />
                      </div>
                      <div>
                        <Text strong>建议动作</Text>
                        <List
                          size="small"
                          dataSource={failureDiagnosis.suggested_actions}
                          renderItem={(item) => <List.Item>{item}</List.Item>}
                        />
                      </div>
                      {failureDiagnosis.artifact_hints.length ? (
                        <div>
                          <Text strong>相关产物</Text>
                          <List
                            size="small"
                            dataSource={failureDiagnosis.artifact_hints}
                            renderItem={(item) => <List.Item>{item}</List.Item>}
                          />
                        </div>
                      ) : null}
                    </Space>
                  </Card>
                ) : null}
                <Card type="inner" title="Trace 预览" style={{ marginBottom: 16 }}>
                  <List
                    dataSource={selectedTask.trace_preview}
                    locale={{ emptyText: '暂无 trace 记录' }}
                    renderItem={(item) => (
                      <List.Item>
                        <div>
                          <Text strong>{String(item.step || '-')}</Text>
                          <Paragraph style={{ marginBottom: 0 }}>{String((item.observation as { summary?: string } | undefined)?.summary || '-')}</Paragraph>
                        </div>
                      </List.Item>
                    )}
                  />
                </Card>
                <Card
                  type="inner"
                  title="任务产物"
                  extra={<Tag color="blue">{artifactItems.length} / {artifactTotal}</Tag>}
                >
                  <Space wrap style={{ marginBottom: 12 }}>
                    <Select
                      value={artifactKindFilter}
                      options={artifactKindOptions}
                      style={{ width: 160 }}
                      onChange={setArtifactKindFilter}
                    />
                    <Input.Search
                      allowClear
                      value={artifactQueryInput}
                      onChange={(event) => setArtifactQueryInput(event.target.value)}
                      onSearch={applyArtifactSearch}
                      placeholder="按文件名、类型或预览检索"
                      style={{ width: 280 }}
                    />
                    <Button onClick={applyArtifactSearch}>检索</Button>
                    <Button onClick={resetArtifactSearch}>重置</Button>
                  </Space>

                  {groupedArtifacts.length === 0 || (groupedArtifacts.length === 1 && groupedArtifacts[0].items.length === 0) ? (
                    <Empty description="暂无匹配产物" />
                  ) : (
                    <Space direction="vertical" style={{ width: '100%' }} size={12}>
                      {groupedArtifacts.map((group) => (
                        <Card
                          key={group.group_key}
                          size="small"
                          type="inner"
                          title={`${group.group_key === 'all' ? '全部产物' : (artifactLabelMap[group.group_key] || group.group_key)} (${group.count})`}
                        >
                          <List
                            loading={artifactLoading}
                            dataSource={group.items}
                            locale={{ emptyText: '暂无任务产物' }}
                            renderItem={(artifact) => (
                              <List.Item
                                actions={[
                                  <Button key="preview" size="small" onClick={() => void previewArtifact(artifact)} loading={previewLoading && previewArtifactId === artifact.artifact_id}>
                                    预览
                                  </Button>,
                                  <Button key="download" size="small" type="primary" ghost onClick={() => downloadArtifact(artifact)}>
                                    下载
                                  </Button>,
                                ]}
                              >
                                <div>
                                  <Space style={{ marginBottom: 6 }}>
                                    <Tag color={artifact.kind === 'diff' ? 'purple' : 'geekblue'}>{artifactLabelMap[artifact.kind] || artifact.kind}</Tag>
                                    <Text code>{artifact.path.split(/[\\/]/).pop() || artifact.artifact_id}</Text>
                                  </Space>
                                  <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{artifact.preview || '暂无预览摘要'}</Paragraph>
                                </div>
                              </List.Item>
                            )}
                          />
                        </Card>
                      ))}
                    </Space>
                  )}
                </Card>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        title="确认建议稿"
        open={approveModalOpen}
        onCancel={() => setApproveModalOpen(false)}
        onOk={() => void approveSelectedTask()}
        confirmLoading={approveSubmitting}
        okText="确认任务"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <div>
            <Text strong>确认人</Text>
            <Input value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} placeholder="请输入确认人" />
          </div>
          <div>
            <Text strong>确认备注</Text>
            <TextArea
              value={approvalNote}
              onChange={(event) => setApprovalNote(event.target.value)}
              placeholder="可填写审批意见、变更说明或风险提示"
              autoSize={{ minRows: 3, maxRows: 6 }}
            />
          </div>
        </Space>
      </Modal>

      <Modal
        title={preview?.filename || '产物预览'}
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

export default TaskCenter
