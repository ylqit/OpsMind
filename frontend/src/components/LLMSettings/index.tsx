/**
 * LLM 配置管理组件
 *
 * 提供多 Provider 的统一管理能力，支持：
 * - 查看与维护 Provider 配置
 * - 测试 Provider 连通性
 * - 设置默认 Provider
 * - 查看最近 AI 调用日志
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  StarOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { aiApi, type LLMCallLogRecord, type LLMProviderRecord } from '@/api/client'

interface LLMProvider extends LLMProviderRecord {
  provider_id: string
}

interface LLMProviderFormValues {
  name: string
  type: string
  api_key?: string
  model: string
  base_url?: string
  enabled: boolean
  timeout: number
  max_retries: number
}

interface ProviderTypeOption {
  value: string
  label: string
  color: string
  apiKeyRequired: boolean
  defaultBaseUrl?: string
  defaultModel?: string
}

// 统一维护 Provider 类型元数据，避免类型扩展时页面多处散落修改。
const PROVIDER_TYPE_OPTIONS: ProviderTypeOption[] = [
  {
    value: 'openai',
    label: 'OpenAI',
    color: 'green',
    apiKeyRequired: true,
    defaultBaseUrl: 'https://api.openai.com/v1',
    defaultModel: 'gpt-4o',
  },
  {
    value: 'anthropic',
    label: 'Anthropic',
    color: 'orange',
    apiKeyRequired: true,
    defaultModel: 'claude-sonnet-4-5-20251001',
  },
  {
    value: 'qwen',
    label: 'Qwen',
    color: 'cyan',
    apiKeyRequired: true,
    defaultBaseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    defaultModel: 'qwen3.5-plus',
  },
  {
    value: 'custom',
    label: '自定义兼容',
    color: 'blue',
    apiKeyRequired: true,
  },
  {
    value: 'openai_compatible',
    label: 'OpenAI Compatible',
    color: 'geekblue',
    apiKeyRequired: false,
    defaultBaseUrl: 'http://127.0.0.1:8000/v1',
    defaultModel: 'custom-model',
  },
  {
    value: 'ollama',
    label: 'Ollama',
    color: 'purple',
    apiKeyRequired: false,
    defaultBaseUrl: 'http://127.0.0.1:11434/v1',
    defaultModel: 'qwen2.5:7b',
  },
  {
    value: 'vllm',
    label: 'vLLM',
    color: 'magenta',
    apiKeyRequired: false,
    defaultBaseUrl: 'http://127.0.0.1:8000/v1',
    defaultModel: 'Qwen/Qwen2.5-7B-Instruct',
  },
  {
    value: 'local_8998',
    label: '本地兼容-8998',
    color: 'volcano',
    apiKeyRequired: false,
    defaultBaseUrl: 'http://127.0.0.1:8998/v1',
    defaultModel: 'local-model',
  },
]

const getProviderTypeOption = (type?: string): ProviderTypeOption | undefined =>
  PROVIDER_TYPE_OPTIONS.find((item) => item.value === type)

const isApiKeyRequired = (type?: string): boolean => Boolean(getProviderTypeOption(type)?.apiKeyRequired)

const LLMSettings: React.FC = () => {
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [defaultProviderId, setDefaultProviderId] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null)
  const [form] = Form.useForm<LLMProviderFormValues>()
  const [testingProviderId, setTestingProviderId] = useState<string | null>(null)
  const [callLogs, setCallLogs] = useState<LLMCallLogRecord[]>([])
  const [callLogsLoading, setCallLogsLoading] = useState(false)

  const selectedProviderType = Form.useWatch('type', form)
  const selectedTypeOption = getProviderTypeOption(selectedProviderType)
  const isEditing = Boolean(editingProviderId)
  const apiKeyRequiredForForm = !isEditing && isApiKeyRequired(selectedProviderType)

  const apiKeyExtraText = useMemo(() => {
    if (selectedTypeOption?.apiKeyRequired) {
      return '该类型建议配置 API Key。编辑时留空表示保持原值。'
    }
    return '本地兼容服务可不填 API Key。编辑时留空表示保持原值。'
  }, [selectedTypeOption])

  const loadProviders = async () => {
    setLoading(true)
    try {
      const data = await aiApi.listProviders()
      setProviders((data.providers || []) as LLMProvider[])
      setDefaultProviderId(data.default_provider_id || '')
    } catch (error) {
      message.error('加载 Provider 列表失败')
    } finally {
      setLoading(false)
    }
  }

  const loadCallLogs = async () => {
    setCallLogsLoading(true)
    try {
      const data = await aiApi.listCallLogs({ limit: 30 })
      setCallLogs(data.items || [])
    } catch (error) {
      message.error('加载调用日志失败')
    } finally {
      setCallLogsLoading(false)
    }
  }

  useEffect(() => {
    void loadProviders()
    void loadCallLogs()
  }, [])

  const canTestProvider = (provider: LLMProvider): boolean => {
    if (!provider.enabled) {
      return false
    }
    if (isApiKeyRequired(provider.type) && !provider.api_key_configured) {
      return false
    }
    return true
  }

  const handleProviderTypeChange = (nextType: string) => {
    const option = getProviderTypeOption(nextType)
    if (!option) {
      return
    }
    const currentBaseUrl = String(form.getFieldValue('base_url') || '').trim()
    const currentModel = String(form.getFieldValue('model') || '').trim()
    if (!currentBaseUrl && option.defaultBaseUrl) {
      form.setFieldValue('base_url', option.defaultBaseUrl)
    }
    if (!currentModel && option.defaultModel) {
      form.setFieldValue('model', option.defaultModel)
    }
    void form.validateFields(['api_key'])
  }

  const handleOpenModal = (provider?: LLMProvider) => {
    if (provider) {
      setEditingProviderId(provider.provider_id)
      form.setFieldsValue({
        name: provider.name,
        type: provider.type,
        model: provider.model,
        base_url: provider.base_url || undefined,
        enabled: provider.enabled,
        timeout: provider.timeout,
        max_retries: provider.max_retries,
        api_key: '',
      })
      setModalVisible(true)
      return
    }

    const defaultOption = getProviderTypeOption('openai')
    setEditingProviderId(null)
    form.resetFields()
    form.setFieldsValue({
      type: 'openai',
      model: defaultOption?.defaultModel || '',
      base_url: defaultOption?.defaultBaseUrl,
      enabled: true,
      timeout: 30,
      max_retries: 2,
    })
    setModalVisible(true)
  }

  const handleSaveProvider = async (values: LLMProviderFormValues) => {
    try {
      if (editingProviderId) {
        const data = await aiApi.updateProvider(editingProviderId, values)
        message.success(data.message || 'Provider 更新成功')
      } else {
        const data = await aiApi.createProvider(values)
        message.success(data.message || 'Provider 创建成功')
      }
      setModalVisible(false)
      await loadProviders()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    }
  }

  const handleDeleteProvider = async (providerId: string) => {
    try {
      const data = await aiApi.deleteProvider(providerId)
      message.success(data.message || 'Provider 删除成功')
      await loadProviders()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleSetDefault = async (providerId: string) => {
    try {
      const data = await aiApi.updateProvider(providerId, { is_default: true })
      message.success(data.message || '默认 Provider 设置成功')
      await loadProviders()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '设置失败')
    }
  }

  const handleTestConnection = async (provider: LLMProvider) => {
    setTestingProviderId(provider.provider_id)
    try {
      const data = await aiApi.testProvider({
        provider_id: provider.provider_id,
        provider_name: provider.name,
        message: '请仅回复 OK',
      })
      if (data.status === 'success') {
        message.success('连接测试成功')
      } else {
        message.error(data.error_message || '连接测试失败')
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '测试连接失败')
    } finally {
      setTestingProviderId(null)
      await loadCallLogs()
    }
  }

  const columns: ColumnsType<LLMProvider> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: LLMProvider) => (
        <Space>
          <span>{name}</span>
          {(record.is_default || defaultProviderId === record.provider_id) && (
            <Tag color="gold">
              <StarOutlined /> 默认
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => {
        const option = getProviderTypeOption(type)
        return <Tag color={option?.color || 'default'}>{option?.label || type}</Tag>
      },
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
    },
    {
      title: '基础 URL',
      dataIndex: 'base_url',
      key: 'base_url',
      render: (url?: string | null) => url || '-',
    },
    {
      title: '状态',
      key: 'status',
      render: (_, record) => (
        <Space>
          <Tag color={record.enabled ? 'green' : 'red'}>{record.enabled ? '启用' : '禁用'}</Tag>
          {isApiKeyRequired(record.type) ? (
            <Tag color={record.api_key_configured ? 'green' : 'red'}>
              {record.api_key_configured ? (
                <>
                  <CheckCircleOutlined /> API Key 已配置
                </>
              ) : (
                <>
                  <CloseCircleOutlined /> API Key 未配置
                </>
              )}
            </Tag>
          ) : (
            <Tag color={record.api_key_configured ? 'green' : 'gold'}>
              {record.api_key_configured ? (
                <>
                  <CheckCircleOutlined /> API Key 已配置
                </>
              ) : (
                <>
                  <CheckCircleOutlined /> API Key 可选
                </>
              )}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testingProviderId === record.provider_id}
            onClick={() => void handleTestConnection(record)}
            disabled={!canTestProvider(record)}
          >
            测试
          </Button>
          <Button
            size="small"
            icon={<StarOutlined />}
            onClick={() => void handleSetDefault(record.provider_id)}
            disabled={record.is_default || defaultProviderId === record.provider_id}
          >
            设为默认
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleOpenModal(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description="确定要删除此 Provider 吗？"
            onConfirm={() => void handleDeleteProvider(record.provider_id)}
            okText="确认"
            cancelText="取消"
          >
            <Button size="small" icon={<DeleteOutlined />} danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const callLogColumns: ColumnsType<LLMCallLogRecord> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString('zh-CN'),
    },
    {
      title: 'Provider',
      dataIndex: 'provider_name',
      key: 'provider_name',
      width: 120,
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
      width: 180,
    },
    {
      title: '端点',
      dataIndex: 'endpoint',
      key: 'endpoint',
      width: 140,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (value: 'success' | 'error') => (
        <Tag color={value === 'success' ? 'green' : 'red'}>{value === 'success' ? '成功' : '失败'}</Tag>
      ),
    },
    {
      title: '延迟',
      dataIndex: 'latency_ms',
      key: 'latency_ms',
      width: 100,
      render: (value: number) => `${value} ms`,
    },
    {
      title: '错误码',
      dataIndex: 'error_code',
      key: 'error_code',
      width: 160,
      render: (value?: string) => value || '-',
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      key: 'error_message',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
  ]

  return (
    <div className="llm-settings">
      <Card
        title="LLM Provider 配置"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenModal()}>
            添加 Provider
          </Button>
        }
      >
        <Tabs
          items={[
            {
              key: 'providers',
              label: 'Provider 列表',
              children: <Table columns={columns} dataSource={providers} loading={loading} rowKey="provider_id" pagination={false} />,
            },
            {
              key: 'call_logs',
              label: '调用日志',
              children: (
                <Table
                  columns={callLogColumns}
                  dataSource={callLogs}
                  loading={callLogsLoading}
                  rowKey="call_id"
                  pagination={{ pageSize: 10 }}
                  size="small"
                  locale={{ emptyText: '暂无调用日志，可先执行连接测试。' }}
                />
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editingProviderId ? '编辑 Provider' : '添加 Provider'}
        open={modalVisible}
        onOk={() => form.submit()}
        onCancel={() => setModalVisible(false)}
        width={640}
      >
        <Form form={form} layout="vertical" onFinish={(values) => void handleSaveProvider(values)}>
          <Form.Item
            name="name"
            label="Provider 名称"
            rules={[
              { required: true, message: '请输入 Provider 名称' },
              { pattern: /^[a-z0-9_]+$/, message: '仅支持小写字母、数字和下划线' },
            ]}
            extra="例如：openai_main、qwen_prod、ollama_local"
          >
            <Input disabled={isEditing} />
          </Form.Item>

          <Form.Item name="type" label="Provider 类型" rules={[{ required: true, message: '请选择 Provider 类型' }]}>
            <Select onChange={handleProviderTypeChange}>
              {PROVIDER_TYPE_OPTIONS.map((item) => (
                <Select.Option key={item.value} value={item.value}>
                  {item.label}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="api_key"
            label="API Key"
            rules={[{ required: apiKeyRequiredForForm, message: '该类型需要 API Key' }]}
            extra={apiKeyExtraText}
          >
            <Input.Password placeholder="请输入 API Key（可选类型可留空）" />
          </Form.Item>

          <Form.Item name="model" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
            <Input placeholder={selectedTypeOption?.defaultModel || '例如：qwen3.5-plus'} />
          </Form.Item>

          <Form.Item
            name="base_url"
            label="API 基础 URL"
            extra="不填写时后端会按 Provider 类型自动补默认地址。"
          >
            <Input placeholder={selectedTypeOption?.defaultBaseUrl || '例如：https://api.openai.com/v1'} />
          </Form.Item>

          <Form.Item name="enabled" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item name="timeout" label="请求超时（秒）">
            <InputNumber min={5} max={300} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item name="max_retries" label="最大重试次数">
            <InputNumber min={0} max={5} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default LLMSettings
