import React from 'react'
import { Result, Button, Spin } from 'antd'
import { useRouteError, useNavigate } from 'react-router-dom'

/**
 * 路由错误边界组件
 */
export const RouteErrorBoundary: React.FC = () => {
  const error = useRouteError() as Error
  const navigate = useNavigate()

  return (
    <Result
      status="error"
      title="页面加载失败"
      subTitle={error?.message || '发生未知错误'}
      extra={[
        <Button type="primary" key="home" onClick={() => navigate('/')}>
          返回首页
        </Button>,
        <Button key="retry" onClick={() => window.location.reload()}>
          刷新页面
        </Button>,
      ]}
    />
  )
}

/**
 * 加载状态组件
 */
export const LoadingFallback: React.FC<{ message?: string }> = ({ message }) => (
  <div
    style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100%',
      minHeight: 400,
    }}
  >
    <Spin size="large" tip={message || '加载中...'} />
  </div>
)

/**
 * 空状态组件
 */
export const EmptyFallback: React.FC<{ message?: string; onRetry?: () => void }> = ({
  message,
  onRetry,
}) => (
  <Result
    status="info"
    title={message || '暂无数据'}
    extra={
      onRetry && (
        <Button type="primary" onClick={onRetry}>
          刷新
        </Button>
      )
    }
  />
)
