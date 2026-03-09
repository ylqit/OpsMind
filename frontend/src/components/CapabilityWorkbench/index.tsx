import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Space, Tag, Modal, Form, Input, Select, Typography, message, Drawer } from 'antd'
import {
  ToolOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  CodeOutlined,
} from '@ant-design/icons'
import { capabilitiesApi } from '@/api/client'

const { Text, Paragraph } = Typography

interface Capability {
  name: string
  description: string
  tags: string[]
  requires_confirmation: boolean
  schema?: any
}

interface CapabilityResult {
  success: boolean
  data?: any
  error?: string
  code?: string
}

export const CapabilityWorkbench: React.FC = () => {
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedCapability, setSelectedCapability] = useState<Capability | null>(null)
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [showExecuteDrawer, setShowExecuteDrawer] = useState(false)
  const [executeResult, setExecuteResult] = useState<CapabilityResult | null>(null)
  const [executing, setExecuting] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    loadCapabilities()
  }, [])

  const loadCapabilities = async () => {
    setLoading(true)
    try {
      const data = await capabilitiesApi.list()
      setCapabilities(data || [])
    } catch (error: any) {
      message.error('加载能力列表失败：' + error.message)
    } finally {
      setLoading(false)
    }
  }

  const viewDetail = async (capability: Capability) => {
    setSelectedCapability(capability)
    try {
      const schema = await capabilitiesApi.getSchema(capability.name)
      setSelectedCapability({ ...capability, schema })
      setShowDetailModal(true)
    } catch (error: any) {
      message.error('加载能力详情失败')
    }
  }

  const handleExecute = async (values: any) => {
    if (!selectedCapability) return

    setExecuting(true)
    try {
      const result = await capabilitiesApi.dispatch(selectedCapability.name, values)
      setExecuteResult({ success: true, data: result })
      message.success('执行成功')
    } catch (error: any) {
      setExecuteResult({ success: false, error: error.message })
      message.error('执行失败：' + error.message)
    } finally {
      setExecuting(false)
      setShowExecuteDrawer(true)
    }
  }

  const columns = [
    {
      title: '能力名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => (
        <Space>
          <ToolOutlined />
          <span style={{ fontFamily: 'monospace' }}>{name}</span>
        </Space>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (tags: string[]) => (
        <Space wrap>
          {tags.map((tag) => (
            <Tag key={tag} color="blue">{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '确认',
      dataIndex: 'requires_confirmation',
      key: 'requires_confirmation',
      render: (required: boolean) => (
        <Tag color={required ? 'orange' : 'green'}>
          {required ? '需要' : '无需'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Capability) => (
        <Space size="small">
          <Button
            size="small"
            icon={<CodeOutlined />}
            onClick={() => viewDetail(record)}
          >
            详情
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => {
              setSelectedCapability(record)
              form.resetFields()
              setShowExecuteDrawer(true)
            }}
          >
            执行
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card
        title="能力调用工作台"
        style={{ margin: 24 }}
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadCapabilities} loading={loading}>
            刷新
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={capabilities}
          loading={loading}
          rowKey="name"
          scroll={{ x: 1000 }}
          size="middle"
        />
      </Card>

      {/* 能力详情 Modal */}
      <Modal
        title="能力详情"
        open={showDetailModal}
        onCancel={() => setShowDetailModal(false)}
        footer={null}
        width={800}
      >
        {selectedCapability && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <div>
              <Text strong>名称：</Text>
              <Text code>{selectedCapability.name}</Text>
            </div>
            <div>
              <Text strong>描述：</Text>
              <Paragraph>{selectedCapability.description}</Paragraph>
            </div>
            <div>
              <Text strong>标签：</Text>
              <Space wrap>
                {selectedCapability.tags.map((tag) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
              </Space>
            </div>
            <div>
              <Text strong>需要确认：</Text>
              <Text>{selectedCapability.requires_confirmation ? '是' : '否'}</Text>
            </div>
            {selectedCapability.schema && (
              <div>
                <Text strong>参数定义：</Text>
                <pre style={{
                  background: '#f5f5f5',
                  padding: 16,
                  borderRadius: 4,
                  maxHeight: 400,
                  overflow: 'auto',
                  fontSize: 12,
                }}>
                  {JSON.stringify(selectedCapability.schema, null, 2)}
                </pre>
              </div>
            )}
          </Space>
        )}
      </Modal>

      {/* 执行能力 Drawer */}
      <Drawer
        title="执行能力"
        placement="right"
        width={600}
        open={showExecuteDrawer}
        onClose={() => {
          setShowExecuteDrawer(false)
          setExecuteResult(null)
        }}
      >
        {selectedCapability && (
          <>
            <Form form={form} layout="vertical" onFinish={handleExecute}>
              <Form.Item
                label="能力名称"
                style={{ marginBottom: 24 }}
              >
                <Input disabled value={selectedCapability.name} />
              </Form.Item>

              <Form.Item
                label="描述"
                style={{ marginBottom: 24 }}
              >
                <Input.TextArea disabled value={selectedCapability.description} rows={2} />
              </Form.Item>

              {/* 通用参数输入区域 - 根据实际能力动态调整 */}
              <Form.Item
                label="参数 (JSON 格式)"
                name="params"
                tooltip="请输入 JSON 格式的参数"
              >
                <Input.TextArea
                  rows={8}
                  placeholder='例如：{"metrics": ["cpu", "memory"]}'
                />
              </Form.Item>

              <Form.Item>
                <Space>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={executing}
                    icon={<PlayCircleOutlined />}
                  >
                    执行
                  </Button>
                  <Button
                    onClick={() => setShowExecuteDrawer(false)}
                    disabled={executing}
                  >
                    取消
                  </Button>
                </Space>
              </Form.Item>
            </Form>

            {/* 执行结果 */}
            {executeResult && (
              <Card
                title="执行结果"
                size="small"
                style={{ marginTop: 16 }}
                bordered={executeResult.success}
              >
                <pre style={{
                  background: executeResult.success ? '#f6ffed' : '#fff2f0',
                  padding: 16,
                  borderRadius: 4,
                  maxHeight: 300,
                  overflow: 'auto',
                  fontSize: 12,
                  fontFamily: 'monospace',
                }}>
                  {JSON.stringify(executeResult, null, 2)}
                </pre>
              </Card>
            )}
          </>
        )}
      </Drawer>
    </>
  )
}
