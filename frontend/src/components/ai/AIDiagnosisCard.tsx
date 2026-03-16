import React from 'react'
import { Card, Col, List, Row, Space, Tag, Typography } from 'antd'
import type { AISummaryRoleViews } from '@/api/client'

const { Paragraph, Text } = Typography

interface AIDiagnosisCardProps {
  summary: string
  riskLevel?: string
  confidence?: number | null
  provider?: string
  parseMode?: string
  supportingText?: string
  primaryCauses?: string[]
  recommendedActions?: string[]
  validationChecks?: string[]
  rollbackPlan?: string[]
  evidenceCitations?: string[]
  roleViews?: AISummaryRoleViews
}

const riskColorMap: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'green',
}

const parseModeLabelMap: Record<string, string> = {
  json: '结构化输出',
  fallback: '降级输出',
}

const roleViewMeta: Array<{ key: keyof AISummaryRoleViews; title: string; color: string }> = [
  { key: 'traffic', title: '流量视角', color: 'blue' },
  { key: 'resource', title: '资源视角', color: 'orange' },
  { key: 'risk', title: '风险视角', color: 'red' },
]

const AIDiagnosisCard: React.FC<AIDiagnosisCardProps> = ({
  summary,
  riskLevel,
  confidence,
  provider,
  parseMode,
  supportingText,
  primaryCauses = [],
  recommendedActions = [],
  validationChecks = [],
  rollbackPlan = [],
  evidenceCitations = [],
  roleViews,
}) => {
  const resolvedRoleViews = roleViewMeta
    .map((item) => {
      const view = roleViews?.[item.key]
      if (!view) {
        return null
      }
      return {
        ...item,
        view,
      }
    })
    .filter(Boolean) as Array<{
      key: keyof AISummaryRoleViews
      title: string
      color: string
      view: NonNullable<AISummaryRoleViews[keyof AISummaryRoleViews]>
    }>

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        {riskLevel ? (
          <Tag color={riskColorMap[riskLevel] || 'default'}>
            风险等级：{riskLevel}
          </Tag>
        ) : null}
        {typeof confidence === 'number' ? (
          <Tag color="geekblue">置信度：{Math.round(confidence * 100)}%</Tag>
        ) : null}
        {provider ? <Tag>{provider}</Tag> : null}
        {parseMode ? <Tag>{parseModeLabelMap[parseMode] || parseMode}</Tag> : null}
      </Space>

      <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{summary}</Paragraph>
      {supportingText ? (
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {supportingText}
        </Paragraph>
      ) : null}

      {resolvedRoleViews.length ? (
        <Row gutter={[12, 12]}>
          {resolvedRoleViews.map((item) => (
            <Col xs={24} md={8} key={item.key}>
              <Card
                size="small"
                title={<Tag color={item.color}>{item.title}</Tag>}
              >
                <Paragraph style={{ marginBottom: 8 }}>{item.view.headline}</Paragraph>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>关键发现</Text>
                <List
                  size="small"
                  dataSource={item.view.key_findings}
                  locale={{ emptyText: '暂无' }}
                  renderItem={(entry) => <List.Item>{entry}</List.Item>}
                  style={{ marginBottom: 8 }}
                />
                <Text strong style={{ display: 'block', marginBottom: 6 }}>建议动作</Text>
                <List
                  size="small"
                  dataSource={item.view.actions}
                  locale={{ emptyText: '暂无' }}
                  renderItem={(entry) => <List.Item>{entry}</List.Item>}
                />
              </Card>
            </Col>
          ))}
        </Row>
      ) : null}

      {primaryCauses.length ? (
        <div>
          <Text strong style={{ display: 'block', marginBottom: 6 }}>可能原因</Text>
          <List
            size="small"
            dataSource={primaryCauses}
            locale={{ emptyText: '暂无' }}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </div>
      ) : null}

      {recommendedActions.length ? (
        <div>
          <Text strong style={{ display: 'block', marginBottom: 6 }}>建议动作</Text>
          <List
            size="small"
            dataSource={recommendedActions}
            locale={{ emptyText: '暂无' }}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </div>
      ) : null}

      {validationChecks.length ? (
        <div>
          <Text strong style={{ display: 'block', marginBottom: 6 }}>验证检查</Text>
          <List
            size="small"
            dataSource={validationChecks}
            locale={{ emptyText: '暂无' }}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </div>
      ) : null}

      {rollbackPlan.length ? (
        <div>
          <Text strong style={{ display: 'block', marginBottom: 6 }}>回滚步骤</Text>
          <List
            size="small"
            dataSource={rollbackPlan}
            locale={{ emptyText: '暂无' }}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </div>
      ) : null}

      {evidenceCitations.length ? (
        <div>
          <Text strong style={{ display: 'block', marginBottom: 6 }}>证据引用</Text>
          <List
            size="small"
            dataSource={evidenceCitations}
            locale={{ emptyText: '暂无' }}
            renderItem={(item) => (
              <List.Item>
                <Text code>{item}</Text>
              </List.Item>
            )}
          />
        </div>
      ) : null}
    </Space>
  )
}

export default AIDiagnosisCard
