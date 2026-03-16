import React from 'react'
import { render, type RenderOptions } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { MemoryRouter } from 'react-router-dom'

interface ProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  route?: string
}

export function renderWithProviders(ui: React.ReactElement, options?: ProvidersOptions) {
  const { route = '/', ...rest } = options || {}

  return render(ui, {
    wrapper: ({ children }) => (
      <ConfigProvider locale={zhCN}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </ConfigProvider>
    ),
    ...rest,
  })
}
