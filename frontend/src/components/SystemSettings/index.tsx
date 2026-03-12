import React, { useEffect, useState } from 'react'
import { Alert, Card, Col, Descriptions, Empty, Row, Space, Spin, Statistic, Tag, Typography } from 'antd'
import { CheckCircleOutlined, InfoCircleOutlined, SettingOutlined } from '@ant-design/icons'
import { dashboardApi, resourcesApi, tasksApi, type DashboardOverview, type ResourceSummary, type TaskRecord } from '@/api/client'

const { Paragraph, Text } = Typography

interface TaskListResponse {
  items: TaskRecord[]
  total: number
}

export const SystemSettings: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [healthStatus, setHealthStatus] = useState<'healthy' | 'unhealthy'>('healthy')
  const [overview, setOverview] = useState<DashboardOverview | null>(null)
  const [resources, setResources] = useState<ResourceSummary | null>(null)
  const [tasks, setTasks] = useState<TaskRecord[]>([])

  const loadSystemInfo = async () => {
    setLoading(true)
    try {
      const [healthRes, overviewRes, resourceRes, taskRes] = await Promise.all([
        fetch('/health').then((response) => response.json()),
        dashboardApi.getOverview({ time_range: '1h' }) as Promise<DashboardOverview>,
        resourcesApi.getSummary({ time_range: '1h' }) as Promise<ResourceSummary>,
        tasksApi.list() as Promise<TaskListResponse>,
      ])
      setHealthStatus(healthRes.status === 'healthy' ? 'healthy' : 'unhealthy')
      setOverview(overviewRes)
      setResources(resourceRes)
      setTasks(taskRes.items || [])
    } catch (error) {
      console.error('加载系统信息失败', error)
      setHealthStatus('unhealthy')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSystemInfo()
  }, [])

  const activeIncidents = overview?.recent_incidents?.length || 0
  const hotServices = overview?.hot_services?.length || 0
  const runningTasks = tasks.filter((item) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(item.status)).length
  const hostCpu = Number(resources?.host?.cpu?.usage_percent || 0)
  const hostMemory = Number(resources?.host?.memory?.usage_percent || 0)

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <SettingOutlined />
            <span>系统设置</span>
          </Space>
        }
        extra={<a onClick={() => void loadSystemInfo()}>刷新</a>}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
          </div>
        ) : (
          <>
            <Alert
              message={
                <Space>
                  {healthStatus === 'healthy' ? (
                    <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 18 }} />
                  ) : (
                    <InfoCircleOutlined style={{ color: '#ff4d4f', fontSize: 18 }} />
                  )}
                  <span>服务状态：<strong>{healthStatus === 'healthy' ? '健康' : '异常'}</strong></span>
                </Space>
              }
              type={healthStatus === 'healthy' ? 'success' : 'error'}
              showIcon
              style={{ marginBottom: 24 }}
            />

            <Row gutter={[16, 16]}>
              <Col xs={24} sm={12} md={6}>
                <Card><Statistic title="活跃异常" value={activeIncidents} suffix="个" /></Card>
              </Col>
              <Col xs={24} sm={12} md={6}>
                <Card><Statistic title="热点服务" value={hotServices} suffix="个" /></Card>
              </Col>
              <Col xs={24} sm={12} md={6}>
                <Card><Statistic title="运行中任务" value={runningTasks} suffix="个" /></Card>
              </Col>
              <Col xs={24} sm={12} md={6}>
                <Card><Statistic title="容器热点" value={resources?.hotspots?.length || 0} suffix="项" /></Card>
              </Col>
            </Row>

            <Descriptions title="主机状态" bordered column={{ xs: 1, sm: 2 }} style={{ marginTop: 24 }}>
              <Descriptions.Item label="CPU 使用率">{hostCpu.toFixed(1)}%</Descriptions.Item>
              <Descriptions.Item label="内存使用率">{hostMemory.toFixed(1)}%</Descriptions.Item>
              <Descriptions.Item label="Docker 数据源">
                <Tag color={(overview?.data_sources?.docker as { configured?: boolean } | undefined)?.configured ? 'green' : 'gold'}>
                  {(overview?.data_sources?.docker as { configured?: boolean } | undefined)?.configured ? '已配置' : '待配置'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Prometheus 数据源">
                <Tag color={(overview?.data_sources?.prometheus as { configured?: boolean } | undefined)?.configured ? 'green' : 'gold'}>
                  {(overview?.data_sources?.prometheus as { configured?: boolean } | undefined)?.configured ? '已配置' : '待配置'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            <Card title="最近任务" style={{ marginTop: 24 }}>
              {tasks.length ? (
                <Descriptions column={1} bordered size="small">
                  {tasks.slice(0, 5).map((task) => (
                    <Descriptions.Item key={task.task_id} label={task.task_type}>
                      <Space>
                        <Tag color={task.status === 'COMPLETED' ? 'green' : task.status === 'FAILED' ? 'red' : 'blue'}>{task.status}</Tag>
                        <Text>{task.progress_message || '无进度说明'}</Text>
                      </Space>
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              ) : (
                <Empty description="暂无任务记录" />
              )}
            </Card>

            <Card title="说明" style={{ marginTop: 24 }}>
              <Paragraph>
                当前系统设置页展示的是服务健康、数据源接入、资源摘要和任务运行概况，便于你从运维主链路查看系统准备情况。
              </Paragraph>
            </Card>
          </>
        )}
      </Card>
    </div>
  )
}

export default SystemSettings
