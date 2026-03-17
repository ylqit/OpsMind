import React from 'react'
import { Button, Card, Empty, List, Space, Tag, Typography } from 'antd'
import type { AIWritebackKind, AIWritebackRecord } from '@/api/client'

const { Paragraph, Text } = Typography

const writebackKindMeta: Record<AIWritebackKind, { label: string; color: string }> = {
  incident_summary_draft: { label: '异常摘要草稿', color: 'blue' },
  recommendation_rationale: { label: '建议说明', color: 'purple' },
  executor_followup: { label: '执行跟进', color: 'cyan' },
}

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

interface AIWritebackListProps {
  items: AIWritebackRecord[]
  title?: string
  emptyDescription?: string
  size?: 'small' | 'default'
  style?: React.CSSProperties
  onOpenTask?: (taskId: string) => void
  onOpenIncident?: (incidentId: string) => void
  onOpenRecommendation?: (recommendationId: string) => void
}

const AIWritebackList: React.FC<AIWritebackListProps> = ({
  items,
  title = 'AI 回写记录',
  emptyDescription = '当前还没有可复用的 AI 回写内容',
  size = 'small',
  style,
  onOpenTask,
  onOpenIncident,
  onOpenRecommendation,
}) => {
  if (!items.length) {
    return (
      <Card type="inner" title={title} size={size} style={style}>
        <Empty description={emptyDescription} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Card>
    )
  }

  return (
    <Card type="inner" title={title} size={size} style={style}>
      <List
        size="small"
        dataSource={items}
        renderItem={(item) => {
          const kindMeta = writebackKindMeta[item.kind] || { label: item.kind, color: 'default' }
          const actionButtons = [
            item.task_id && onOpenTask
              ? (
                <Button key={`task-${item.writeback_id}`} size="small" onClick={() => onOpenTask(item.task_id as string)}>
                  打开任务
                </Button>
              )
              : null,
            item.incident_id && onOpenIncident
              ? (
                <Button
                  key={`incident-${item.writeback_id}`}
                  size="small"
                  type="link"
                  onClick={() => onOpenIncident(item.incident_id as string)}
                >
                  查看异常
                </Button>
              )
              : null,
            item.recommendation_id && onOpenRecommendation
              ? (
                <Button
                  key={`recommendation-${item.writeback_id}`}
                  size="small"
                  type="link"
                  onClick={() => onOpenRecommendation(item.recommendation_id as string)}
                >
                  查看建议
                </Button>
              )
              : null,
          ].filter(Boolean)

          return (
            <List.Item actions={actionButtons.length ? actionButtons : undefined}>
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color={kindMeta.color}>{kindMeta.label}</Tag>
                  <Text strong>{item.title}</Text>
                  {item.provider ? <Tag>{item.provider}</Tag> : null}
                  <Tag color={item.status === 'success' ? 'green' : item.status === 'degraded' ? 'gold' : 'default'}>
                    {item.status || 'unknown'}
                  </Tag>
                  <Text type="secondary">{formatDateTime(item.created_at)}</Text>
                </Space>
                {item.summary ? (
                  <Paragraph style={{ marginBottom: 0 }}>
                    {item.summary}
                  </Paragraph>
                ) : null}
                <Paragraph ellipsis={{ rows: 3, expandable: true, symbol: '展开' }} style={{ marginBottom: 0 }}>
                  {item.content}
                </Paragraph>
                <Space wrap>
                  {item.claims.length ? <Tag color="blue">结论 {item.claims.length}</Tag> : null}
                  {item.command_suggestions.length ? <Tag color="cyan">命令建议 {item.command_suggestions.length}</Tag> : null}
                  {item.task_id ? <Tag color="geekblue">任务 {item.task_id}</Tag> : null}
                </Space>
              </Space>
            </List.Item>
          )
        }}
      />
    </Card>
  )
}

export default AIWritebackList
