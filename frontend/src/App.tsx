import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import {
  DashboardOutlined,
  WarningOutlined,
  BoxPlotOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { Dashboard } from './components/Dashboard'
import { AlertPanel } from './components/AlertPanel'
import { ContainerList } from './components/ContainerList'
import { AlertRules } from './components/AlertRules'
import { SystemSettings } from './components/SystemSettings'

const { Header, Content, Sider } = Layout

const App: React.FC = () => {
  const [collapsed, setCollapsed] = React.useState(false)

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: '监控仪表盘',
    },
    {
      key: '/alerts',
      icon: <WarningOutlined />,
      label: '告警管理',
    },
    {
      key: '/alert-rules',
      icon: <SettingOutlined />,
      label: '告警规则',
    },
    {
      key: '/containers',
      icon: <BoxPlotOutlined />,
      label: '容器管理',
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '系统设置',
    },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div style={{
          height: 32,
          margin: 16,
          background: 'rgba(255, 255, 255, 0.2)',
          borderRadius: 4,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 'bold',
        }}>
          {collapsed ? 'ops' : 'opsMind'}
        </div>
        <Menu
          theme="dark"
          defaultSelectedKeys={['/']}
          mode="inline"
          items={menuItems}
          onClick={({ key }) => {
            window.location.href = key
          }}
        />
      </Sider>
      <Layout>
        <Header style={{
          padding: '0 24px',
          background: '#fff',
          display: 'flex',
          alignItems: 'center',
          boxShadow: '0 1px 4px rgba(0,21,41,.08)',
        }}>
          <h2 style={{ margin: 0 }}>智能运维助手</h2>
        </Header>
        <Content style={{ margin: '16px' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/alerts" element={<AlertPanel />} />
            <Route path="/alert-rules" element={<AlertRules />} />
            <Route path="/containers" element={<ContainerList />} />
            <Route path="/settings" element={<SystemSettings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

export default App
