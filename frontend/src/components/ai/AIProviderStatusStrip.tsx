import React from 'react'
import { Button, Card, Skeleton, Space, Tag, Typography } from 'antd'
import type { AIAssistantStatusResponse } from '@/api/client'

const { Paragraph, Text } = Typography

interface AIProviderStatusStripProps {
  status: AIAssistantStatusResponse | null
  loading?: boolean
  onOpenSettings?: () => void
  extra?: React.ReactNode
}

const statusMeta: Record<AIAssistantStatusResponse['status'], { label: string; color: string }> = {
  ready: { label: 'AI 已就绪', color: 'green' },
  degraded: { label: 'AI 降级中', color: 'gold' },
  unavailable: { label: 'AI 不可用', color: 'red' },
}

const providerSourceLabelMap: Record<AIAssistantStatusResponse['provider_source'], string> = {
  router: '路由',
  repository: '配置仓储',
  none: '未识别',
}

const buildProviderHint = (status: AIAssistantStatusResponse) => {
  if (status.default_provider && status.default_model) {
    return `默认 Provider：${status.default_provider} / ${status.default_model}`
  }
  if (status.default_provider) {
    return `默认 Provider：${status.default_provider}`
  }
  if (status.router_default_provider) {
    return `当前路由默认 Provider：${status.router_default_provider}`
  }
  return '当前还没有默认 Provider 信息'
}

const AIProviderStatusStrip: React.FC<AIProviderStatusStripProps> = ({
  status,
  loading = false,
  onOpenSettings,
  extra,
}) => {
  if (loading) {
    return (
      <Card className="ops-surface-card" size="small" style={{ marginBottom: 16 }}>
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      </Card>
    )
  }

  if (!status) {
    return null
  }

  const meta = statusMeta[status.status]

  return (
    <Card
      className="ops-surface-card"
      size="small"
      style={{ marginBottom: 16 }}
      extra={
        <Space wrap>
          {extra}
          {onOpenSettings ? (
            <Button type="link" size="small" onClick={onOpenSettings}>
              前往 LLM 设置
            </Button>
          ) : null}
        </Space>
      }
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Text strong>AI 运行状态</Text>
          <Tag color={meta.color}>{meta.label}</Tag>
          <Tag color={status.provider_ready ? 'green' : 'default'}>路由：{status.provider_ready ? '可用' : '未就绪'}</Tag>
          <Tag>已启用 {status.enabled_providers}</Tag>
          <Tag>可识别模型 {status.configured_providers}</Tag>
        </Space>
        <Paragraph style={{ marginBottom: 0 }}>
          {status.status_message}
        </Paragraph>
        <Space wrap>
          <Tag color="geekblue">{buildProviderHint(status)}</Tag>
          <Tag>来源：{providerSourceLabelMap[status.provider_source]}</Tag>
        </Space>
      </Space>
    </Card>
  )
}

export default AIProviderStatusStrip
