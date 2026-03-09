import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, Drawer, Typography, RefreshButton, message } from 'antd'
import {
  DockerOutlined,
  ReloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { containersApi } from '@/api/client'

interface Container {
  id: string
  name: string
  image: string
  status: string
  state: string
}

interface ContainerDetail {
  container: {
    id: string
    name: string
    image: string
    status: string
    state: {
      Status: string
      Running: boolean
      ExitCode?: number
      OOMKilled?: boolean
    }
    created: string
    network: {
      IPAddress?: string
      Ports?: Record<string, any>
    }
  }
  diagnosis: {
    status: string
    running: boolean
    healthy: boolean | null
    issues: string[]
    recommendations: string[]
  }
  logs?: string
}

export const ContainerList: React.FC = () => {
  const [containers, setContainers] = useState<Container[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedContainer, setSelectedContainer] = useState<string | null>(null)
  const [detail, setDetail] = useState<ContainerDetail | null>(null)
  const [showDetailDrawer, setShowDetailDrawer] = useState(false)
  const [showLogsDrawer, setShowLogsDrawer] = useState(false)
  const [containerLogs, setContainerLogs] = useState<string>('')

  useEffect(() => {
    loadContainers()
  }, [])

  const loadContainers = async () => {
    setLoading(true)
    try {
      const data = await containersApi.list()
      setContainers(data.containers || [])
    } catch (error) {
      message.error('获取容器列表失败')
    } finally {
      setLoading(false)
    }
  }

  const viewDetail = async (name: string) => {
    try {
      const data = await containersApi.get(name)
      setDetail(data)
      setSelectedContainer(name)
      setShowDetailDrawer(true)
    } catch (error) {
      message.error('获取容器详情失败')
    }
  }

  const viewLogs = async (name: string) => {
    try {
      const data = await containersApi.getLogs(name, 100)
      setContainerLogs(data.logs || data.container?.logs || '暂无日志')
      setSelectedContainer(name)
      setShowLogsDrawer(true)
    } catch (error) {
      message.error('获取容器日志失败')
    }
  }

  const columns = [
    {
      title: '容器 ID',
      dataIndex: 'id',
      key: 'id',
      render: (id: string) => <span style={{ fontFamily: 'monospace' }}>{id}</span>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '镜像',
      dataIndex: 'image',
      key: 'image',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const color = status === 'running' ? 'green' : status === 'exited' ? 'red' : 'gray'
        return <Tag color={color}>{status}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Container) => (
        <Space size="small">
          <Button
            size="small"
            icon={<DockerOutlined />}
            onClick={() => viewDetail(record.name)}
          >
            详情
          </Button>
          <Button
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => viewLogs(record.name)}
          >
            日志
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card
        title="容器管理"
        style={{ margin: 24 }}
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadContainers} loading={loading}>
            刷新
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={containers}
          loading={loading}
          rowKey="id"
          scroll={{ x: 800 }}
        />
      </Card>

      {/* 容器详情 Drawer */}
      <Drawer
        title="容器详情"
        placement="right"
        width={600}
        open={showDetailDrawer}
        onClose={() => {
          setShowDetailDrawer(false)
          setDetail(null)
        }}
      >
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <div>
              <Typography.Text strong>名称：</Typography.Text>
              <Typography.Text>{detail.container.name}</Typography.Text>
            </div>
            <div>
              <Typography.Text strong>镜像：</Typography.Text>
              <Typography.Text>{detail.container.image}</Typography.Text>
            </div>
            <div>
              <Typography.Text strong>状态：</Typography.Text>
              <Tag color={detail.container.status === 'running' ? 'green' : 'red'}>
                {detail.container.status}
              </Tag>
            </div>
            <div>
              <Typography.Text strong>运行时间：</Typography.Text>
              <Typography.Text>{detail.container.created}</Typography.Text>
            </div>
            {detail.container.network?.IPAddress && (
              <div>
                <Typography.Text strong>IP 地址：</Typography.Text>
                <Typography.Text>{detail.container.network.IPAddress}</Typography.Text>
              </div>
            )}

            <Typography.Title level={5}>诊断报告</Typography.Title>
            <div>
              <Typography.Text strong>健康状态：</Typography.Text>
              <Tag color={
                detail.diagnosis.healthy === true ? 'green' :
                detail.diagnosis.healthy === false ? 'red' : 'gray'
              }>
                {detail.diagnosis.healthy === true ? '健康' :
                 detail.diagnosis.healthy === false ? '异常' : '未知'}
              </Tag>
            </div>
            {detail.diagnosis.issues && detail.diagnosis.issues.length > 0 && (
              <div>
                <Typography.Text strong>问题：</Typography.Text>
                <ul>
                  {detail.diagnosis.issues.map((issue, idx) => (
                    <li key={idx}>{issue}</li>
                  ))}
                </ul>
              </div>
            )}
            {detail.diagnosis.recommendations && detail.diagnosis.recommendations.length > 0 && (
              <div>
                <Typography.Text strong>建议：</Typography.Text>
                <ul>
                  {detail.diagnosis.recommendations.map((rec, idx) => (
                    <li key={idx}>{rec}</li>
                  ))}
                </ul>
              </div>
            )}
          </Space>
        )}
      </Drawer>

      {/* 日志 Drawer */}
      <Drawer
        title="容器日志"
        placement="right"
        width={800}
        open={showLogsDrawer}
        onClose={() => {
          setShowLogsDrawer(false)
          setContainerLogs('')
        }}
      >
        <pre style={{
          background: '#f5f5f5',
          padding: 16,
          borderRadius: 4,
          maxHeight: '100%',
          overflow: 'auto',
          fontSize: 12,
          fontFamily: 'monospace',
        }}>
          {containerLogs}
        </pre>
      </Drawer>
    </>
  )
}
