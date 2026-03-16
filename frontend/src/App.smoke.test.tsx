import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from './test/renderWithProviders'

// 主控台路由页依赖较多，这里统一 mock 为占位组件，只验证壳层与路由行为。
vi.mock('./pages/OverviewDashboard', () => ({
  default: () => <div>OverviewDashboard Smoke</div>,
}))
vi.mock('./pages/TrafficAnalytics', () => ({
  default: () => <div>TrafficAnalytics Smoke</div>,
}))
vi.mock('./pages/ResourceAnalytics', () => ({
  default: () => <div>ResourceAnalytics Smoke</div>,
}))
vi.mock('./pages/IncidentCenter', () => ({
  default: () => <div>IncidentCenter Smoke</div>,
}))
vi.mock('./pages/RecommendationCenter', () => ({
  default: () => <div>RecommendationCenter Smoke</div>,
}))
vi.mock('./pages/TaskCenter', () => ({
  default: () => <div>TaskCenter Smoke</div>,
}))
vi.mock('./pages/QualityMetrics', () => ({
  default: () => <div>QualityMetrics Smoke</div>,
}))
vi.mock('./pages/AIAssistantWorkbench', () => ({
  default: () => <div>AIAssistantWorkbench Smoke</div>,
}))
vi.mock('./pages/ExecutorPlugins', () => ({
  default: () => <div>ExecutorPlugins Smoke</div>,
}))
vi.mock('./components/CapabilityWorkbench', () => ({
  CapabilityWorkbench: () => <div>CapabilityWorkbench Smoke</div>,
}))
vi.mock('./components/SystemSettings', () => ({
  SystemSettings: () => <div>SystemSettings Smoke</div>,
}))
vi.mock('./components/LLMSettings', () => ({
  default: () => <div>LLMSettings Smoke</div>,
}))
vi.mock('./components/ErrorBoundary', () => ({
  RouteErrorBoundary: () => <div>RouteErrorBoundary Smoke</div>,
  LoadingFallback: ({ message }: { message?: string }) => <div>{message || 'Loading...'}</div>,
}))

import App from './App'

describe('App smoke', () => {
  it('renders shell and default overview route', () => {
    renderWithProviders(<App />, { route: '/' })

    expect(screen.getByText('统一运维分析工作台')).toBeTruthy()
    expect(screen.getByText('主控台')).toBeTruthy()
    expect(screen.getByText('总览')).toBeTruthy()
    expect(screen.getByText('OverviewDashboard Smoke')).toBeTruthy()
  })

  it('redirects unknown path to overview route', () => {
    renderWithProviders(<App />, { route: '/path-not-exists' })
    expect(screen.getByText('OverviewDashboard Smoke')).toBeTruthy()
  })
})
