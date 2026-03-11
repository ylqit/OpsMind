import React, { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Descriptions, Empty, List, Row, Space, Table, Tag, Typography } from 'antd'
import { tasksApi, type TaskDetailResponse, type TaskRecord } from '@/api/client'
import { useTaskEventStream } from '@/hooks/useTaskEventStream'

const { Paragraph, Text, Title } = Typography

interface TaskListResponse {
  items: TaskRecord[]
  total: number
}

export const TaskCenter: React.FC = () => {
  const [loading, setLoading] = useState(true)
  const [tasks, setTasks] = useState<TaskRecord[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskDetailResponse | null>(null)

  const loadTasks = useCallback(async () => {
    setLoading(true)
    try {
      const response = (await tasksApi.list()) as TaskListResponse
      setTasks(response.items)
      if (response.items[0]) {
        const detail = (await tasksApi.get(response.items[0].task_id)) as TaskDetailResponse
        setSelectedTask(detail)
      } else {
        setSelectedTask(null)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const loadTaskDetail = useCallback(async (taskId: string) => {
    const detail = (await tasksApi.get(taskId)) as TaskDetailResponse
    setSelectedTask(detail)
  }, [])

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

  const approveSelectedTask = async () => {
    if (!selectedTask) {
      return
    }
    await tasksApi.approve(selectedTask.task.task_id)
    await loadTaskDetail(selectedTask.task.task_id)
    await loadTasks()
  }

  const cancelSelectedTask = async () => {
    if (!selectedTask) {
      return
    }
    await tasksApi.cancel(selectedTask.task.task_id)
    await loadTaskDetail(selectedTask.task.task_id)
    await loadTasks()
  }

  return (
    <div className="ops-page">
      <div className="ops-page__hero">
        <div>
          <Title level={2} style={{ marginBottom: 8 }}>任务中心</Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(15, 23, 42, 0.72)' }}>
            跟踪分析、报表和建议任务的状态流、证据片段和产物输出，避免执行过程不可见。
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
                { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'COMPLETED' ? 'green' : value === 'FAILED' ? 'red' : value === 'WAITING_CONFIRM' ? 'gold' : 'blue'}>{value}</Tag> },
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
                <Button onClick={() => void approveSelectedTask()} disabled={selectedTask?.task.status !== 'WAITING_CONFIRM'}>确认</Button>
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
                </Descriptions>
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
                <Card type="inner" title="任务产物">
                  <List
                    dataSource={selectedTask.artifacts}
                    locale={{ emptyText: '暂无任务产物' }}
                    renderItem={(artifact) => (
                      <List.Item>
                        <div>
                          <Text code>{artifact.path}</Text>
                          <Paragraph style={{ marginBottom: 0 }}>{artifact.preview}</Paragraph>
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

export default TaskCenter
