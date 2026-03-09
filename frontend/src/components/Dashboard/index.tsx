import React, { useEffect, useState } from 'react'
import { Row, Col, Card, Progress, Statistic, Alert, Table, Tag, Space, Button, RefreshButton } from 'antd'
import {
  CPUOutlined,
  DashboardOutlined,
  HddOutlined,
  WifiOutlined,
  WarningOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useMonitorStore } from '@/stores/monitorStore'
import { useAlertStore } from '@/stores/alertStore'

interface HostMetrics {
  cpu?: {
    usage_percent: number
    cpu_count: number
  }
  memory?: {
    usage_percent: number
    available_mb: number
  }
  disk?: {
    partitions: Array<{
      mountpoint: string
      usage_percent: number
    }>
  }
  network?: {
    bytes_sent_mb: number
    bytes_recv_mb: number
  }
  alerts?: Array<{
    level: string
    metric: string
    message: string
    suggestion: string
  }>
}

export const Dashboard: React.FC = () => {
  const { hostMetrics, hostLoading, hostError, fetchHostMetrics } = useMonitorStore()
  const { alerts, fetchAlerts } = useAlertStore()
  const [activeAlerts, setActiveAlerts] = useState<any[]>([])

  useEffect(() => {
    loadData()
    // 每分钟刷新
    const interval = setInterval(loadData, 60000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (hostMetrics?.alerts) {
      setActiveAlerts(hostMetrics.alerts)
    } else if (alerts.length > 0) {
      setActiveAlerts(alerts.filter(a => a.status === 'active'))
    }
  }, [hostMetrics, alerts])

  const loadData = async () => {
    await fetchHostMetrics()
    await fetchAlerts('active')
  }

  const getUsageColor = (percent: number) => {
    if (percent > 90) return '#ff4d4f'
    if (percent > 70) return '#faad14'
    return '#52c41a'
  }

  const alertColumns = [
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      render: (level: string) => (
        <Tag color={level === 'critical' ? 'red' : 'orange'}>
          {level === 'critical' ? '严重' : '警告'}
        </Tag>
      ),
    },
    {
      title: '指标',
      dataIndex: 'metric',
      key: 'metric',
      render: (metric: string) => {
        const metricNames: Record<string, string> = {
          cpu_usage: 'CPU 使用率',
          memory_usage: '内存使用率',
          disk_usage: '磁盘使用率',
        }
        return metricNames[metric] || metric
      },
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
    },
  ]

  return (
    <div className="dashboard" style={{ padding: 24 }}>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <h2>资源监控仪表盘</h2>
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={hostLoading}>
          刷新
        </Button>
      </div>

      {hostError && (
        <Alert
          message="数据加载失败"
          description={hostError}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Row gutter={[16, 16]}>
        {/* CPU 卡片 */}
        <Col xs={24} sm={12} lg={6}>
          <Card
            title={
              <Space>
                <CPUOutlined />
                <span>CPU</span>
              </Space>
            }
          >
            <Progress
              type="dashboard"
              percent={Math.round(hostMetrics?.cpu?.usage_percent || 0)}
              strokeColor={{
                '0%': '#108ee9',
                '100%': getUsageColor(hostMetrics?.cpu?.usage_percent || 0),
              }}
              format={(percent?: number) => `${percent}%`}
            />
            <div style={{ marginTop: 16, textAlign: 'center' }}>
              <Statistic
                title="核心数"
                value={hostMetrics?.cpu?.cpu_count || 0}
                suffix="核"
              />
            </div>
          </Card>
        </Col>

        {/* 内存卡片 */}
        <Col xs={24} sm={12} lg={6}>
          <Card
            title={
              <Space>
                <DashboardOutlined />
                <span>内存</span>
              </Space>
            }
          >
            <Progress
              type="dashboard"
              percent={Math.round(hostMetrics?.memory?.usage_percent || 0)}
              strokeColor={{
                '0%': '#108ee9',
                '100%': getUsageColor(hostMetrics?.memory?.usage_percent || 0),
              }}
              format={(percent?: number) => `${percent}%`}
            />
            <div style={{ marginTop: 16, textAlign: 'center' }}>
              <Statistic
                title="可用内存"
                value={Math.round((hostMetrics?.memory?.available_mb || 0) / 1024)}
                suffix="GB"
              />
            </div>
          </Card>
        </Col>

        {/* 磁盘卡片 */}
        <Col xs={24} sm={12} lg={6}>
          <Card
            title={
              <Space>
                <HddOutlined />
                <span>磁盘</span>
              </Space>
            }
          >
            {hostMetrics?.disk?.partitions?.slice(0, 3).map((partition, idx) => (
              <div key={idx} style={{ marginBottom: 12 }}>
                <div style={{ marginBottom: 4, display: 'flex', justifyContent: 'space-between' }}>
                  <span>{partition.mountpoint}</span>
                  <span>{partition.usage_percent}%</span>
                </div>
                <Progress
                  percent={partition.usage_percent}
                  strokeColor={getUsageColor(partition.usage_percent)}
                  size="small"
                />
              </div>
            ))}
            {!hostMetrics?.disk?.partitions && <div style={{ color: '#999' }}>暂无数据</div>}
          </Card>
        </Col>

        {/* 网络卡片 */}
        <Col xs={24} sm={12} lg={6}>
          <Card
            title={
              <Space>
                <WifiOutlined />
                <span>网络</span>
              </Space>
            }
          >
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title="发送"
                  value={Math.round(hostMetrics?.network?.bytes_sent_mb || 0)}
                  suffix="MB"
                  valueStyle={{ fontSize: 16 }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="接收"
                  value={Math.round(hostMetrics?.network?.bytes_recv_mb || 0)}
                  suffix="MB"
                  valueStyle={{ fontSize: 16 }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* 告警区域 */}
      {activeAlerts && activeAlerts.length > 0 && (
        <Alert
          type="warning"
          message="检测到资源告警"
          description={
            <Table
              columns={alertColumns}
              dataSource={activeAlerts}
              rowKey="metric"
              pagination={false}
              size="small"
              scroll={{ y: 200 }}
            />
          }
          showIcon
          style={{ marginTop: 16 }}
          action={
            <Space>
              <Button type="link" onClick={() => window.location.href = '/alerts'}>
                查看告警管理
              </Button>
            </Space>
          }
        />
      )}
    </div>
  )
}
