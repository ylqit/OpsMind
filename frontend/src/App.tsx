import React from 'react'
import { Layout, Menu } from 'antd'
import {
  AlertOutlined,
  AppstoreOutlined,
  AreaChartOutlined,
  BarChartOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { CapabilityWorkbench } from './components/CapabilityWorkbench'
import { SystemSettings } from './components/SystemSettings'
import LLMSettings from './components/LLMSettings'
import OverviewDashboard from './pages/OverviewDashboard'
import TrafficAnalytics from './pages/TrafficAnalytics'
import ResourceAnalytics from './pages/ResourceAnalytics'
import IncidentCenter from './pages/IncidentCenter'
import RecommendationCenter from './pages/RecommendationCenter'
import TaskCenter from './pages/TaskCenter'
import QualityMetrics from './pages/QualityMetrics'
import ExecutorPlugins from './pages/ExecutorPlugins'
import { RouteErrorBoundary, LoadingFallback } from './components/ErrorBoundary'

const { Header, Content, Sider } = Layout

const menuItems = [
  { key: '/', icon: <AppstoreOutlined />, label: '总览' },
  { key: '/traffic', icon: <AreaChartOutlined />, label: '流量分析' },
  { key: '/resources', icon: <DeploymentUnitOutlined />, label: '资源分析' },
  { key: '/incidents', icon: <AlertOutlined />, label: '异常中心' },
  { key: '/recommendations', icon: <ExperimentOutlined />, label: '建议中心' },
  { key: '/tasks', icon: <ThunderboltOutlined />, label: '任务中心' },
  { key: '/quality', icon: <BarChartOutlined />, label: '质量看板' },
  { key: '/executors', icon: <ToolOutlined />, label: '执行插件' },
  { key: '/workbench', icon: <ToolOutlined />, label: '能力调试' },
  { key: '/llm-settings', icon: <ThunderboltOutlined />, label: 'LLM 配置' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

const AppLayout: React.FC = () => {
  const [collapsed, setCollapsed] = React.useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <Layout style={{ minHeight: '100vh', background: '#f4f7fb' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="light" width={256}>
        <div className="ops-brand-block">
          <div className="ops-brand-block__mark">ops</div>
          {!collapsed ? (
            <div>
              <div className="ops-brand-block__title">opsMind</div>
              <div className="ops-brand-block__subtitle">智能运维主控台</div>
            </div>
          ) : null}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>
      <Layout>
        <Header className="ops-app-header">
          <div>
            <div className="ops-app-header__title">统一运维分析工作台</div>
            <div className="ops-app-header__subtitle">入口流量、资源压力、异常结论和建议草稿统一查看</div>
          </div>
        </Header>
        <Content style={{ padding: 20 }}>
          <React.Suspense fallback={<LoadingFallback message="页面加载中..." />}>
            <Routes>
              <Route path="/" element={<OverviewDashboard />} />
              <Route path="/traffic" element={<TrafficAnalytics />} />
              <Route path="/resources" element={<ResourceAnalytics />} />
              <Route path="/incidents" element={<IncidentCenter />} />
              <Route path="/recommendations" element={<RecommendationCenter />} />
              <Route path="/tasks" element={<TaskCenter />} />
              <Route path="/quality" element={<QualityMetrics />} />
              <Route path="/executors" element={<ExecutorPlugins />} />
              <Route path="/workbench" element={<CapabilityWorkbench />} />
              <Route path="/llm-settings" element={<LLMSettings />} />
              <Route path="/settings" element={<SystemSettings />} />
              <Route path="/error" element={<RouteErrorBoundary />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </React.Suspense>
        </Content>
      </Layout>
    </Layout>
  )
}

const App: React.FC = () => <AppLayout />

export default App
