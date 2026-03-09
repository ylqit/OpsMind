import React, { useEffect, useState } from 'react'
import { Card, Descriptions, Tag, Space, Statistic, Row, Col, Progress, Spin, Alert } from 'antd'
import {
  ServerOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'

interface SystemInfo {
  version: string
  python_version?: string
  platform?: string
  capabilities_count?: number
  active_alerts?: number
  alert_rules_count?: number
}

interface DiagnoseInfo {
  system: {
    cpu_usage: number
    memory_usage: number
    memory_available_mb: number
    disk_usage: number
    disk_free_gb: number
  }
  services: {
    docker: {
      status: string
      containers: number
    }
    alerts: {
      active: number
      rules: number
    }
  }
}

export const SystemSettings: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [systemInfo, setSystemInfo] = useState<SystemInfo>({ version: '0.1.0' })
  const [healthStatus, setHealthStatus] = useState<'healthy' | 'unhealthy'>('healthy')
  const [diagnoseInfo, setDiagnoseInfo] = useState<DiagnoseInfo | null>(null)

  useEffect(() => {
    loadSystemInfo()
  }, [])

  const loadSystemInfo = async () => {
    setLoading(true)
    try {
      // 健康检查
      const healthRes = await fetch('/health')
      const healthData = await healthRes.json()
      setHealthStatus(healthData.status === 'healthy' ? 'healthy' : 'unhealthy')

      // 获取能力列表
      const capsRes = await fetch('/api/capabilities')
      const capsData = await capsRes.json()

      // 获取告警数量
      const alertsRes = await fetch('/api/alerts?limit=1')
      const alertsData = await alertsRes.json()

      // 获取规则数量
      const rulesRes = await fetch('/api/alerts/rules')
      const rulesData = await rulesRes.json()

      // 获取诊断信息
      const diagnoseRes = await fetch('/api/diagnose')
      const diagnoseData = await diagnoseRes.json()

      setSystemInfo({
        version: healthData.version || '0.1.0',
        capabilities_count: capsData.length,
        active_alerts: alertsData.total,
        alert_rules_count: rulesData.total,
      })
      setDiagnoseInfo(diagnoseData)
    } catch (error) {
      console.error('加载系统信息失败:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '24px', maxWidth: '100%', overflowX: 'hidden' }}>
      <Card
        title={
          <Space>
            <ServerOutlined />
            系统设置
          </Space>
        }
        style={{ marginBottom: 24 }}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
          </div>
        ) : (
          <>
            {/* 健康状态 */}
            <Alert
              message={
                <Space>
                  {healthStatus === 'healthy' ? (
                    <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 20 }} />
                  ) : (
                    <InfoCircleOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
                  )}
                  <span>系统状态：<strong>{healthStatus === 'healthy' ? '健康' : '异常'}</strong></span>
                </Space>
              }
              type={healthStatus === 'healthy' ? 'success' : 'error'}
              showIcon
              style={{ marginBottom: 24 }}
            />

            {/* 系统信息 */}
            <Descriptions
              title="系统信息"
              bordered
              column={{ xs: 1, sm: 2, md: 2 }}
            >
              <Descriptions.Item label="系统版本">
                v{systemInfo.version}
              </Descriptions.Item>
              <Descriptions.Item label="能力数量">
                {systemInfo.capabilities_count || 0}
              </Descriptions.Item>
              <Descriptions.Item label="活动告警">
                {systemInfo.active_alerts || 0}
              </Descriptions.Item>
              <Descriptions.Item label="告警规则">
                {systemInfo.alert_rules_count || 0}
              </Descriptions.Item>
            </Descriptions>

            {/* 资源监控详情 */}
            {diagnoseInfo && (
              <>
                <Descriptions
                  title="资源使用"
                  bordered
                  column={{ xs: 1, sm: 2, md: 3 }}
                  style={{ marginTop: 24 }}
                >
                  <Descriptions.Item label="CPU 使用率">
                    {diagnoseInfo.system.cpu_usage}%
                  </Descriptions.Item>
                  <Descriptions.Item label="内存使用率">
                    {diagnoseInfo.system.memory_usage}%
                  </Descriptions.Item>
                  <Descriptions.Item label="可用内存">
                    {diagnoseInfo.system.memory_available_mb} GB
                  </Descriptions.Item>
                  <Descriptions.Item label="磁盘使用率">
                    {diagnoseInfo.system.disk_usage}%
                  </Descriptions.Item>
                  <Descriptions.Item label="磁盘剩余">
                    {diagnoseInfo.system.disk_free_gb} GB
                  </Descriptions.Item>
                </Descriptions>

                {/* 服务状态 */}
                <Descriptions
                  title="服务状态"
                  bordered
                  column={{ xs: 1, sm: 2, md: 2 }}
                  style={{ marginTop: 24 }}
                >
                  <Descriptions.Item label="Docker">
                    <Tag color={diagnoseInfo.services.docker.status === 'available' ? 'green' : 'red'}>
                      {diagnoseInfo.services.docker.status === 'available' ? '可用' : '不可用'}
                    </Tag>
                    {diagnoseInfo.services.docker.containers} 个容器
                  </Descriptions.Item>
                  <Descriptions.Item label="告警系统">
                    <Tag color="blue">运行中</Tag>
                    {diagnoseInfo.services.alerts.active} 活动 / {diagnoseInfo.services.alerts.rules} 规则
                  </Descriptions.Item>
                </Descriptions>
              </>
            )}
          </>
        )}
      </Card>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]}>{/* xs: 24, sm: 12, md: 8 */}
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title="监控能力"
              value={systemInfo.capabilities_count || 0}
              suffix="个"
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title="活动告警"
              value={systemInfo.active_alerts || 0}
              suffix="条"
              valueStyle={{ color: systemInfo.active_alerts && systemInfo.active_alerts > 0 ? '#ff4d4f' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title="告警规则"
              value={systemInfo.alert_rules_count || 0}
              suffix="条"
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 功能说明 */}
      <Card title="功能说明" style={{ marginTop: 24 }}>
        <Descriptions column={1}>
          <Descriptions.Item label="主机监控">
            实时监控 CPU、内存、磁盘、网络等系统资源，自动检测阈值并生成告警
          </Descriptions.Item>
          <Descriptions.Item label="容器诊断">
            支持 Docker 容器状态查询、日志获取、健康诊断
          </Descriptions.Item>
          <Descriptions.Item label="日志分析">
            分析日志文件，识别错误模式（异常、超时、内存、连接等）
          </Descriptions.Item>
          <Descriptions.Item label="K8s YAML 生成">
            自动生成 Kubernetes Deployment、Service、ConfigMap、Ingress 配置
          </Descriptions.Item>
          <Descriptions.Item label="告警管理">
            支持告警规则配置、告警查询、确认、解决等全生命周期管理
          </Descriptions.Item>
          <Descriptions.Item label="修复预案">
            内置 CPU 过高、内存过高、磁盘满、容器崩溃等场景的修复预案
          </Descriptions.Item>
          <Descriptions.Item label="实时推送">
            通过 WebSocket 实时推送新告警通知，支持自动重连
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 关于 */}
      <Card title="关于 opsMind" style={{ marginTop: 24 }}>
        <p>
          <strong>opsMind</strong> 是一个智能运维助手，提供可控、可追溯的运维诊断与告警管理能力。
        </p>
        <p style={{ color: '#666', fontSize: 14 }}>
          版本：v{systemInfo.version} | License: Apache 2.0
        </p>
      </Card>
    </div>
  )
}
