/**
 * 修复预案查看与执行组件
 *
 * 提供修复预案的查看、预演和执行功能
 * 支持：
 * - 预案列表查看
 * - 预案详情展示（步骤、风险等级、预计时间）
 * - 预演模式（dry run）
 * - 执行修复步骤
 * - 查看执行结果
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Button,
  Space,
  Tag,
  Modal,
  Descriptions,
  Steps,
  message,
  Spin,
  Alert,
  Divider,
  Collapse,
  Typography,
  Result,
  Progress,
} from 'antd';
import {
  ToolOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

const { Text, Paragraph, Title } = Typography;
const { Panel } = Collapse;

/**
 * 修复预案接口
 */
interface RemediationPlan {
  id: string;
  name: string;
  description: string;
  trigger: {
    metric: string;
    operator: string;
    threshold?: number;
    value?: string | number;
  };
  steps: RemediationStep[];
  estimated_time: string;
  risk_level: 'low' | 'medium' | 'high';
}

/**
 * 修复步骤接口
 */
interface RemediationStep {
  order: number;
  name: string;
  action: string;
  description: string;
  command?: string;
  risk: 'low' | 'medium' | 'high';
  rollback?: string | null;
}

/**
 * 执行结果接口
 */
interface ExecutionResult {
  step: number;
  name: string;
  success: boolean;
  output?: string;
  error?: string;
}

/**
 * 修复预案组件
 */
const RemediationView: React.FC = () => {
  const [plans, setPlans] = useState<RemediationPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<RemediationPlan | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showExecuteModal, setShowExecuteModal] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executionResults, setExecutionResults] = useState<ExecutionResult[]>([]);
  const [executionComplete, setExecutionComplete] = useState(false);
  const [selectedSteps, setSelectedSteps] = useState<number[]>([]);

  /**
   * 获取修复预案列表
   */
  const fetchPlans = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/remediation/plans');
      const data = await response.json();
      setPlans(data);
    } catch (error) {
      message.error('获取修复预案列表失败');
      console.error('Failed to fetch plans:', error);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchPlans();
  }, []);

  /**
   * 获取预案详情
   */
  const fetchPlanDetail = async (planId: string) => {
    try {
      const response = await fetch(`/api/remediation/plans/${planId}`);
      const data = await response.json();
      setSelectedPlan(data);
      setShowDetailModal(true);
    } catch (error) {
      message.error('获取预案详情失败');
      console.error('Failed to fetch plan detail:', error);
    }
  };

  /**
   * 获取风险等级标签颜色
   */
  const getRiskColor = (risk: string) => {
    switch (risk) {
      case 'low':
        return 'green';
      case 'medium':
        return 'orange';
      case 'high':
        return 'red';
      default:
        return 'default';
    }
  };

  /**
   * 获取风险等级文本
   */
  const getRiskText = (risk: string) => {
    switch (risk) {
      case 'low':
        return '低风险';
      case 'medium':
        return '中风险';
      case 'high':
        return '高风险';
      default:
        return risk;
    }
  };

  /**
   * 预案列表表格列定义
   */
  const columns: ColumnsType<RemediationPlan> = [
    {
      title: '预案 ID',
      dataIndex: 'id',
      key: 'id',
      width: 180,
    },
    {
      title: '预案名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '触发条件',
      key: 'trigger',
      render: (_, record) => (
        <Tag color="blue">
          {record.trigger.metric} {record.trigger.operator} {record.trigger.threshold ?? record.trigger.value}
        </Tag>
      ),
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      render: (risk: string) => (
        <Tag color={getRiskColor(risk)}>{getRiskText(risk)}</Tag>
      ),
    },
    {
      title: '预计时间',
      dataIndex: 'estimated_time',
      key: 'estimated_time',
      width: 120,
    },
    {
      title: '步骤数',
      key: 'steps',
      width: 80,
      render: (_, record) => record.steps.length,
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => fetchPlanDetail(record.id)}
          >
            查看
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => handleShowExecute(record)}
          >
            执行
          </Button>
        </Space>
      ),
    },
  ];

  /**
   * 显示执行弹窗
   */
  const handleShowExecute = (plan: RemediationPlan) => {
    setSelectedPlan(plan);
    setSelectedSteps(plan.steps.map((_, idx) => idx));
    setExecutionResults([]);
    setExecutionComplete(false);
    setShowExecuteModal(true);
  };

  /**
   * 执行修复预案
   */
  const handleExecute = async (dryRun: boolean = false) => {
    if (!selectedPlan) return;

    setExecuting(true);
    setExecutionResults([]);
    setExecutionComplete(false);

    try {
      const response = await fetch('/api/remediation/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_id: selectedPlan.id,
          step_indices: selectedSteps,
          dry_run: dryRun,
        }),
      });

      const data = await response.json();

      if (dryRun) {
        message.success('预演完成，请查看执行计划');
        setExecutionResults(
          data.steps?.map((step: any, idx: number) => ({
            step: idx + 1,
            name: step.name,
            success: true,
            output: step.description,
          })) || []
        );
      } else {
        if (data.results) {
          setExecutionResults(data.results);
          const allSuccess = data.results.every((r: any) => r.success);
          if (allSuccess) {
            message.success('修复执行完成');
          } else {
            message.warning('部分步骤执行失败');
          }
          setExecutionComplete(true);
        }
      }
    } catch (error) {
      message.error('执行失败：' + (error as Error).message);
      console.error('Execution error:', error);
    }

    setExecuting(false);
  };

  return (
    <div className="remediation-view">
      <Card
        title={
          <Space>
            <ToolOutlined />
            <span>修复预案库</span>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={fetchPlans}>
            刷新
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={plans}
          loading={loading}
          rowKey="id"
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* 预案详情弹窗 */}
      <Modal
        title={
          <Space>
            <FileTextOutlined />
            <span>{selectedPlan?.name}</span>
          </Space>
        }
        open={showDetailModal}
        onCancel={() => setShowDetailModal(false)}
        footer={[
          <Button
            key="execute"
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => {
              setShowDetailModal(false);
              handleShowExecute(selectedPlan!);
            }}
          >
            执行此预案
          </Button>,
          <Button
            key="close"
            onClick={() => setShowDetailModal(false)}
          >
            关闭
          </Button>,
        ]}
        width={800}
      >
        {selectedPlan && (
          <>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="预案 ID">{selectedPlan.id}</Descriptions.Item>
              <Descriptions.Item label="描述">{selectedPlan.description}</Descriptions.Item>
              <Descriptions.Item label="触发条件">
                <Tag color="blue">
                  {selectedPlan.trigger.metric} {selectedPlan.trigger.operator}{' '}
                  {selectedPlan.trigger.threshold ?? selectedPlan.trigger.value}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="风险等级">
                <Tag color={getRiskColor(selectedPlan.risk_level)}>
                  {getRiskText(selectedPlan.risk_level)}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="预计时间">{selectedPlan.estimated_time}</Descriptions.Item>
            </Descriptions>

            <Divider orientation="left">修复步骤</Divider>

            <Steps
              direction="vertical"
              size="small"
              items={selectedPlan.steps.map((step, idx) => ({
                title: step.name,
                description: (
                  <>
                    <Text type="secondary">{step.description}</Text>
                    <div style={{ marginTop: 8 }}>
                      <Tag color={getRiskColor(step.risk)}>{getRiskText(step.risk)}</Tag>
                      {step.command && (
                        <Text code style={{ marginLeft: 8 }}>{step.command}</Text>
                      )}
                    </div>
                    {step.rollback && (
                      <Alert
                        type="info"
                        message={`回滚方案：${step.rollback}`}
                        style={{ marginTop: 8 }}
                        showIcon
                        size="small"
                      />
                    )}
                  </>
                ),
                icon: step.action === 'analyze' ? (
                  <ThunderboltOutlined />
                ) : (
                  <CheckCircleOutlined />
                ),
              }))}
            />
          </>
        )}
      </Modal>

      {/* 执行弹窗 */}
      <Modal
        title={
          <Space>
            <PlayCircleOutlined />
            <span>执行修复预案</span>
          </Space>
        }
        open={showExecuteModal}
        onCancel={() => setShowExecuteModal(false)}
        footer={null}
        width={800}
      >
        {selectedPlan && (
          <>
            {!executionComplete && executionResults.length === 0 && (
              <>
                <Alert
                  type="warning"
                  message="执行修复操作前请仔细阅读步骤"
                  description="部分操作可能需要一定时间，执行过程中请勿关闭窗口"
                  showIcon
                  style={{ marginBottom: 16 }}
                />

                <Title level={5}>选择要执行的步骤</Title>
                <Collapse defaultActiveKey={['steps']}>
                  <Panel header="步骤列表" key="steps">
                    {selectedPlan.steps.map((step, idx) => (
                      <div key={idx} style={{ marginBottom: 12 }}>
                        <Space>
                          <input
                            type="checkbox"
                            checked={selectedSteps.includes(idx)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedSteps([...selectedSteps, idx]);
                              } else {
                                setSelectedSteps(selectedSteps.filter((s) => s !== idx));
                              }
                            }}
                          />
                          <Text strong>{step.order}. {step.name}</Text>
                          <Tag color={getRiskColor(step.risk)}>{getRiskText(step.risk)}</Tag>
                        </Space>
                        <Text type="secondary" style={{ marginLeft: 24, display: 'block' }}>
                          {step.description}
                        </Text>
                      </div>
                    ))}
                  </Panel>
                </Collapse>

                <Divider />

                <Space style={{ marginTop: 16 }}>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={() => handleExecute(false)}
                    loading={executing}
                    disabled={selectedSteps.length === 0}
                  >
                    执行选定步骤
                  </Button>
                  <Button
                    icon={<ThunderboltOutlined />}
                    onClick={() => handleExecute(true)}
                    loading={executing}
                  >
                    预演
                  </Button>
                </Space>
              </>
            )}

            {(executionResults.length > 0 || executing) && (
              <>
                {executing && (
                  <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <Spin size="large" tip="正在执行修复..." />
                    <Progress
                      percent={Math.round(
                        (executionResults.length / selectedPlan.steps.length) * 100
                      )}
                      style={{ marginTop: 16 }}
                    />
                  </div>
                )}

                {!executing && (
                  <>
                    <Result
                      status={
                        executionResults.every((r) => r.success)
                          ? 'success'
                          : 'warning'
                      }
                      title={
                        executionResults.every((r) => r.success)
                          ? '修复执行完成'
                          : '修复执行完成（部分失败）'
                      }
                      subTitle={
                        executionResults.every((r) => r.success)
                          ? '所有步骤已成功执行'
                          : '请检查失败步骤的错误信息'
                      }
                    />

                    <Collapse defaultActiveKey={['results']}>
                      <Panel header="执行结果" key="results">
                        {executionResults.map((result, idx) => (
                          <Card
                            key={idx}
                            size="small"
                            type="inner"
                            style={{
                              marginBottom: 12,
                              borderLeft: `4px solid ${
                                result.success ? '#52c41a' : '#ff4d4f'
                              }`,
                            }}
                          >
                            <Space>
                              {result.success ? (
                                <CheckCircleOutlined style={{ color: '#52c41a' }} />
                              ) : (
                                <ExclamationCircleOutlined
                                  style={{ color: '#ff4d4f' }}
                                />
                              )}
                              <Text strong>
                                步骤 {result.step}: {result.name}
                              </Text>
                            </Space>
                            {result.output && (
                              <Paragraph
                                code
                                style={{
                                  marginTop: 8,
                                  marginLeft: 24,
                                  background: '#f5f5f5',
                                  padding: 8,
                                  borderRadius: 4,
                                }}
                              >
                                {result.output}
                              </Paragraph>
                            )}
                            {result.error && (
                              <Alert
                                type="error"
                                message={result.error}
                                style={{ marginTop: 8, marginLeft: 24 }}
                                showIcon
                                size="small"
                              />
                            )}
                          </Card>
                        ))}
                      </Panel>
                    </Collapse>

                    <Space style={{ marginTop: 16 }}>
                      <Button onClick={() => setShowExecuteModal(false)}>
                        关闭
                      </Button>
                      <Button
                        icon={<ReloadOutlined />}
                        onClick={() => {
                          setExecutionResults([]);
                          setExecutionComplete(false);
                        }}
                      >
                        重新执行
                      </Button>
                    </Space>
                  </>
                )}
              </>
            )}
          </>
        )}
      </Modal>
    </div>
  );
};

export default RemediationView;
