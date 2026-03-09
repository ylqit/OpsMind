/**
 * LLM 配置管理组件
 *
 * 提供多 LLM Provider 配置管理界面，支持：
 * - 查看已配置的 Provider 列表
 * - 添加/编辑/删除 Provider
 * - 测试连接
 * - 设置默认 Provider
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Button,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  InputNumber,
  message,
  Popconfirm,
  Descriptions,
  Tabs
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SettingOutlined,
  StarOutlined,
  ThunderboltOutlined
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

interface LLMProvider {
  name: string;
  type: string;
  model: string;
  base_url?: string;
  enabled: boolean;
  timeout: number;
  api_key_configured: boolean;
}

interface LLMProviderFormValues {
  name: string;
  type: string;
  api_key?: string;
  model: string;
  base_url?: string;
  enabled: boolean;
  timeout: number;
}

const LLMSettings: React.FC = () => {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [testingProvider, setTestingProvider] = useState<string | null>(null);

  // 加载 Provider 列表
  const loadProviders = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/llm/providers');
      const data = await response.json();
      setProviders(data.providers || []);
      setDefaultProvider(data.default_provider || 'openai');
    } catch (error) {
      message.error('加载 Provider 列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProviders();
  }, []);

  // 打开编辑/新建弹窗
  const handleOpenModal = (provider?: LLMProvider) => {
    if (provider) {
      setEditingProvider(provider.name);
      form.setFieldsValue({
        name: provider.name,
        type: provider.type,
        model: provider.model,
        base_url: provider.base_url,
        enabled: provider.enabled,
        timeout: provider.timeout,
        api_key: '' // API Key 不显示已有值
      });
    } else {
      setEditingProvider(null);
      form.resetFields();
    }
    setModalVisible(true);
  };

  // 保存 Provider
  const handleSaveProvider = async (values: LLMProviderFormValues) => {
    try {
      const url = editingProvider
        ? `/api/llm/providers/${editingProvider}`
        : '/api/llm/providers';
      const method = editingProvider ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values)
      });

      const data = await response.json();

      if (response.ok) {
        message.success(data.message);
        setModalVisible(false);
        loadProviders();
      } else {
        message.error(data.detail || '操作失败');
      }
    } catch (error) {
      message.error('保存失败');
    }
  };

  // 删除 Provider
  const handleDeleteProvider = async (name: string) => {
    try {
      const response = await fetch(`/api/llm/providers/${name}`, {
        method: 'DELETE'
      });
      const data = await response.json();

      if (response.ok) {
        message.success(data.message);
        loadProviders();
      } else {
        message.error(data.detail || '删除失败');
      }
    } catch (error) {
      message.error('删除失败');
    }
  };

  // 设置默认 Provider
  const handleSetDefault = async (name: string) => {
    try {
      const response = await fetch('/api/llm/default-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_name: name })
      });
      const data = await response.json();

      if (response.ok) {
        message.success(data.message);
        setDefaultProvider(name);
      } else {
        message.error(data.detail || '设置失败');
      }
    } catch (error) {
      message.error('设置失败');
    }
  };

  // 测试连接
  const handleTestConnection = async (name: string) => {
    setTestingProvider(name);
    try {
      const response = await fetch(`/api/llm/providers/${name}/test`, {
        method: 'POST'
      });
      const data = await response.json();

      if (data.status === 'success') {
        message.success(data.message);
      } else {
        message.error(data.message);
      }
    } catch (error) {
      message.error('测试连接失败');
    } finally {
      setTestingProvider(null);
    }
  };

  const columns: ColumnsType<LLMProvider> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: LLMProvider) => (
        <Space>
          <span>{name}</span>
          {defaultProvider === name && (
            <Tag color="gold">
              <StarOutlined /> 默认
            </Tag>
          )}
        </Space>
      )
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => {
        const typeMap: Record<string, { color: string; text: string }> = {
          openai: { color: 'green', text: 'OpenAI' },
          anthropic: { color: 'orange', text: 'Anthropic' },
          custom: { color: 'blue', text: '自定义' }
        };
        const t = typeMap[type] || { color: 'default', text: type };
        return <Tag color={t.color}>{t.text}</Tag>;
      }
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model'
    },
    {
      title: '基础 URL',
      dataIndex: 'base_url',
      key: 'base_url',
      render: (url?: string) => url || '-'
    },
    {
      title: '状态',
      key: 'status',
      render: (_, record) => (
        <Space>
          <Tag color={record.enabled ? 'green' : 'red'}>
            {record.enabled ? '启用' : '禁用'}
          </Tag>
          <Tag color={record.api_key_configured ? 'green' : 'red'}>
            {record.api_key_configured ? (
              <><CheckCircleOutlined /> API Key 已配置</>
            ) : (
              <><CloseCircleOutlined /> API Key 未配置</>
            )}
          </Tag>
        </Space>
      )
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testingProvider === record.name}
            onClick={() => handleTestConnection(record.name)}
            disabled={!record.api_key_configured}
          >
            测试
          </Button>
          <Button
            size="small"
            icon={<StarOutlined />}
            onClick={() => handleSetDefault(record.name)}
            disabled={defaultProvider === record.name}
          >
            设为默认
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleOpenModal(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description="确定要删除此 Provider 吗？"
            onConfirm={() => handleDeleteProvider(record.name)}
            okText="确认"
            cancelText="取消"
          >
            <Button
              size="small"
              icon={<DeleteOutlined />}
              danger
              disabled={record.name === 'openai' || record.name === 'anthropic'}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      )
    }
  ];

  return (
    <div className="llm-settings">
      <Card
        title="LLM Provider 配置"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => handleOpenModal()}
          >
            添加 Provider
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={providers}
          loading={loading}
          rowKey="name"
          pagination={false}
        />
      </Card>

      {/* 添加/编辑弹窗 */}
      <Modal
        title={editingProvider ? '编辑 Provider' : '添加 Provider'}
        open={modalVisible}
        onOk={() => form.submit()}
        onCancel={() => setModalVisible(false)}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSaveProvider}
          initialValues={{
            type: 'openai',
            enabled: true,
            timeout: 30
          }}
        >
          <Form.Item
            name="name"
            label="Provider 名称"
            rules={[
              { required: true, message: '请输入 Provider 名称' },
              { pattern: /^[a-z0-9_]+$/, message: '只能包含小写字母、数字和下划线' }
            ]}
            extra="例如：openai, anthropic, custom-llm"
          >
            <Input disabled={!!editingProvider} />
          </Form.Item>

          <Form.Item
            name="type"
            label="Provider 类型"
            rules={[{ required: true, message: '请选择 Provider 类型' }]}
          >
            <Select>
              <Select.Option value="openai">OpenAI（兼容 OpenAI API）</Select.Option>
              <Select.Option value="anthropic">Anthropic（Claude API）</Select.Option>
              <Select.Option value="custom">自定义（其他 OpenAI 兼容 API）</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="api_key"
            label="API Key"
            rules={[
              { required: !editingProvider, message: '请输入 API Key' }
            ]}
            extra="建议使用环境变量管理敏感密钥"
          >
            <Input.Password placeholder="请输入 API Key" />
          </Form.Item>

          <Form.Item
            name="model"
            label="模型名称"
            rules={[{ required: true, message: '请输入模型名称' }]}
          >
            <Input placeholder="例如：gpt-4o, claude-sonnet-4-5-20251001" />
          </Form.Item>

          <Form.Item
            name="base_url"
            label="API 基础 URL"
            extra="OpenAI 和 Anthropic 类型可不填，自定义类型必填"
          >
            <Input placeholder="例如：https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item
            name="enabled"
            label="启用状态"
            valuePropName="checked"
          >
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item
            name="timeout"
            label="请求超时（秒）"
          >
            <InputNumber min={1} max={300} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default LLMSettings;
