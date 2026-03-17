import React from 'react'
import { Button, Card, Empty, List, Space, Tag, Typography } from 'antd'
import type { AIAssistantStatusResponse } from '@/api/client'

const { Paragraph, Text } = Typography

interface AIInlineAssistantCardProps {
  title: string
  description: string
  status?: AIAssistantStatusResponse | null
  runLabel: string
  onRun: () => void
  runLoading?: boolean
  runDisabled?: boolean
  onOpenAssistant?: () => void
  openAssistantLabel?: string
  summary?: string
  riskLevel?: string
  confidence?: number | null
  provider?: string
  parseMode?: string
  nextActions?: string[]
  limitations?: string[]
  citations?: string[]
  claimsCount?: number
  writebackCount?: number
  emptyDescription?: string
}

const riskColorMap: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'green',
}

const statusMeta: Record<AIAssistantStatusResponse['status'], { label: string; color: string }> = {
  ready: { label: 'AI 已就绪', color: 'green' },
  degraded: { label: 'AI 降级中', color: 'gold' },
  unavailable: { label: 'AI 不可用', color: 'red' },
}

const parseModeLabelMap: Record<string, string> = {
  json: '结构化输出',
  fallback: '降级输出',
}

const AIInlineAssistantCard: React.FC<AIInlineAssistantCardProps> = ({
  title,
  description,
  status,
  runLabel,
  onRun,
  runLoading = false,
  runDisabled = false,
  onOpenAssistant,
  openAssistantLabel = '打开 AI 助手',
  summary,
  riskLevel,
  confidence,
  provider,
  parseMode,
  nextActions = [],
  limitations = [],
  citations = [],
  claimsCount = 0,
  writebackCount = 0,
  emptyDescription = '当前还没有 AI 结果，可以先在这里发起一次页内诊断。',
}) => {
  const meta = status ? statusMeta[status.status] : null
  const compactNextActions = nextActions.slice(0, 3)
  const compactLimitations = limitations.slice(0, 2)

  return (
    <Card
      type="inner"
      title={title}
      size="small"
      extra={
        <Space wrap>
          <Button size="small" type="primary" onClick={onRun} loading={runLoading} disabled={runDisabled}>
            {runLabel}
          </Button>
          {onOpenAssistant ? (
            <Button size="small" onClick={onOpenAssistant}>
              {openAssistantLabel}
            </Button>
          ) : null}
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {description}
        </Paragraph>

        <Space wrap>
          {meta ? <Tag color={meta.color}>{meta.label}</Tag> : null}
          {status ? <Tag color={status.provider_ready ? 'green' : 'default'}>路由 {status.provider_ready ? '可用' : '未就绪'}</Tag> : null}
          {typeof claimsCount === 'number' && claimsCount > 0 ? <Tag color="blue">结论 {claimsCount}</Tag> : null}
          {typeof writebackCount === 'number' && writebackCount > 0 ? <Tag color="cyan">回写 {writebackCount}</Tag> : null}
        </Space>

        {summary ? (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space wrap>
              {riskLevel ? <Tag color={riskColorMap[riskLevel] || 'default'}>风险 {riskLevel}</Tag> : null}
              {typeof confidence === 'number' ? <Tag color="geekblue">置信度 {Math.round(confidence * 100)}%</Tag> : null}
              {provider ? <Tag>{provider}</Tag> : null}
              {parseMode ? <Tag>{parseModeLabelMap[parseMode] || parseMode}</Tag> : null}
            </Space>
            <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{summary}</Paragraph>

            {compactNextActions.length ? (
              <div>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>下一步动作</Text>
                <List
                  size="small"
                  dataSource={compactNextActions}
                  split={false}
                  renderItem={(item) => <List.Item style={{ paddingInline: 0, paddingBlock: 2 }}>{item}</List.Item>}
                />
              </div>
            ) : null}

            {compactLimitations.length ? (
              <div>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>限制项</Text>
                <List
                  size="small"
                  dataSource={compactLimitations}
                  split={false}
                  renderItem={(item) => (
                    <List.Item style={{ paddingInline: 0, paddingBlock: 2 }}>
                      <Text type="secondary">{item}</Text>
                    </List.Item>
                  )}
                />
              </div>
            ) : null}

            {citations.length ? (
              <Text type="secondary">证据引用 {citations.length} 条，可在当前详情里继续展开。</Text>
            ) : null}
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyDescription} />
        )}
      </Space>
    </Card>
  )
}

export default AIInlineAssistantCard
