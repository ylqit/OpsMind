import React from 'react'
import { Alert, Button, Empty, Space, Typography } from 'antd'

const { Text } = Typography

interface PageStatusBannerProps {
  type?: 'success' | 'info' | 'warning' | 'error'
  title: string
  description?: React.ReactNode
  actionText?: string
  onAction?: () => void
}

interface CardEmptyStateProps {
  title?: string
  description?: React.ReactNode
  actionText?: string
  onAction?: () => void
}

export const PageStatusBanner: React.FC<PageStatusBannerProps> = ({
  type = 'info',
  title,
  description,
  actionText,
  onAction,
}) => (
  <Alert
    type={type}
    showIcon
    message={title}
    description={description}
    action={actionText && onAction ? <Button size="small" type="link" onClick={onAction}>{actionText}</Button> : undefined}
    style={{ marginBottom: 16 }}
  />
)

export const CardEmptyState: React.FC<CardEmptyStateProps> = ({
  title = '暂无数据',
  description,
  actionText,
  onAction,
}) => (
  <Empty
    image={Empty.PRESENTED_IMAGE_SIMPLE}
    description={(
      <Space direction="vertical" size={4}>
        <Text strong>{title}</Text>
        {description ? <Text type="secondary">{description}</Text> : null}
      </Space>
    )}
  >
    {actionText && onAction ? <Button onClick={onAction}>{actionText}</Button> : null}
  </Empty>
)
