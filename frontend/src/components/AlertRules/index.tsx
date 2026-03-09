import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Space, Modal, Form, Input, InputNumber, Select, Switch, message, Typography } from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useAlertStore } from '@/stores/alertStore'

const { Text } = Typography

export const AlertRules: React.FC = () => {
  const { rules, rulesLoading, fetchRules, createRule, deleteRule } = useAlertStore()
  const [showModal, setShowModal] = useState(false)
  const [editingRule, setEditingRule] = useState<any>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    loadRules()
  }, [])

  const loadRules = () => {
    fetchRules()
  }

  const handleCreate = () => {
    setEditingRule(null)
    form.resetFields()
    setShowModal(true)
  }

  const handleEdit = (record: any) => {
    setEditingRule(record)
    form.setFieldsValue(record)
    setShowModal(true)
  }

  const handleDelete = async (record: any) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除规则 "${record.name}" 吗？`,
      onOk: async () => {
        try {
          await deleteRule(record.id)
          message.success('规则已删除')
        } catch (error) {
          message.error('删除失败')
        }
      },
    })
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      await createRule(values)
      message.success(editingRule ? '规则已更新' : '规则已创建')
      setShowModal(false)
      loadRules()
    } catch (error) {
      console.error('验证失败:', error)
    }
  }

  const columns = [
    {
      title: '规则名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '监控指标',
      dataIndex: 'metric',
      key: 'metric',
      render: (metric: string) => {
        const metricNames: Record<string, string> = {
          cpu_usage: 'CPU 使用率',
          memory_usage: '内存使用率',
          disk_usage_c: 'C 盘使用率',
          disk_usage_d: 'D 盘使用率',
        }
        return metricNames[metric] || metric
      },
    },
    {
      title: '阈值条件',
      key: 'threshold',
      render: (_: any, record: any) => (
        <span>{record.operator} {record.threshold}</span>
      ),
    },
    {
      title: '严重程度',
      dataIndex: 'severity',
      key: 'severity',
      render: (severity: string) => {
        const colorMap: Record<string, string> = {
          info: 'blue',
          warning: 'orange',
          critical: 'red',
        }
        return <span style={{ color: colorMap[severity] }}>{severity}</span>
      },
    },
    {
      title: '状态',
      key: 'enabled',
      render: (enabled: boolean) => (
        <span style={{ color: enabled ? '#52c41a' : '#999' }}>
          {enabled ? '已启用' : '已禁用'}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: any) => (
        <Space size="small">
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card
        title="告警规则配置"
        style={{ margin: 24 }}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadRules} loading={rulesLoading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
              新建规则
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={rules}
          loading={rulesLoading}
          rowKey="id"
          scroll={{ x: 800 }}
        />
      </Card>

      {/* 新建/编辑规则 Modal */}
      <Modal
        title={editingRule ? '编辑规则' : '新建规则'}
        open={showModal}
        onOk={handleSubmit}
        onCancel={() => setShowModal(false)}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            operator: '>',
            severity: 'warning',
            enabled: true,
          }}
        >
          <Form.Item
            name="name"
            label="规则名称"
            rules={[{ required: true, message: '请输入规则名称' }]}
          >
            <Input placeholder="例如：CPU 过高告警" />
          </Form.Item>

          <Form.Item
            name="metric"
            label="监控指标"
            rules={[{ required: true, message: '请选择监控指标' }]}
          >
            <Select>
              <Select.Option value="cpu_usage">CPU 使用率</Select.Option>
              <Select.Option value="memory_usage">内存使用率</Select.Option>
              <Select.Option value="disk_usage_c">C 盘使用率</Select.Option>
              <Select.Option value="disk_usage_d">D 盘使用率</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="operator"
            label="比较运算符"
            rules={[{ required: true, message: '请选择比较运算符' }]}
          >
            <Select>
              <Select.Option value=">">&gt; 大于</Select.Option>
              <Select.Option value=">=">&ge; 大于等于</Select.Option>
              <Select.Option value="<">&lt; 小于</Select.Option>
              <Select.Option value="<=">&le; 小于等于</Select.Option>
              <Select.Option value="=">= 等于</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="threshold"
            label="阈值"
            rules={[{ required: true, message: '请输入阈值' }]}
          >
            <InputNumber
              min={0}
              max={100}
              precision={1}
              style={{ width: '100%' }}
              placeholder="例如：80"
            />
          </Form.Item>

          <Form.Item
            name="severity"
            label="严重程度"
            rules={[{ required: true, message: '请选择严重程度' }]}
          >
            <Select>
              <Select.Option value="info">信息 (info)</Select.Option>
              <Select.Option value="warning">警告 (warning)</Select.Option>
              <Select.Option value="critical">严重 (critical)</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="enabled"
            label="启用状态"
            valuePropName="checked"
          >
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
