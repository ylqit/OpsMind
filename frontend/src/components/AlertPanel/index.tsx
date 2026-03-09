import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, Modal, Typography, Drawer, Steps, StepProps, message } from 'antd'
import {
  WarningOutlined,
  CheckOutlined,
  CloseOutlined,
  ToolOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useAlertStore } from '@/stores/alertStore'

interface Alert {
  id: string
  level: string
  metric: string
  message: string
  suggestion: string
  created_at: string
  status: string
  severity: string
}

export const AlertPanel: React.FC = () => {
  const { alerts, alertsLoading, fetchAlerts, acknowledgeAlert, resolveAlert, plans, fetchPlans, getPlan, selectedPlan, executePlan } = useAlertStore()
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null)
  const [showPlanModal, setShowPlanModal] = useState(false)
  const [showExecuteDrawer, setShowExecuteDrawer] = useState(false)
  const [executingSteps, setExecutingSteps] = useState<number[]>([])
  const [executeResults, setExecuteResults] = useState<any[]>([])

  useEffect(() => {
    loadAlerts()
    fetchPlans()
  }, [])

  const loadAlerts = () => {
    fetchAlerts()
  }

  const handleAcknowledge = async (alertId: string) => {
    try {
      await acknowledgeAlert(alertId)
      message.success('告警已确认')
    } catch (error) {
      message.error('确认告警失败')
    }
  }

  const handleResolve = async (alertId: string) => {
    try {
      await resolveAlert(alertId)
      message.success('告警已解决')
    } catch (error) {
      message.error('解决告警失败')
    }
  }

  const showRemediation = async (alert: Alert) => {
    setSelectedAlert(alert)
    // 根据告警类型匹配预案
    const planMap: Record<string, string> = {
      cpu_usage: 'cpu_high',
      memory_usage: 'memory_high',
      disk_usage: 'disk_full',
    }
    const planId = planMap[alert.metric]
    if (planId) {
      try {
        await getPlan(planId)
        setShowPlanModal(true)
      } catch (error) {
        message.error('获取预案失败')
      }
    } else {
      message.warning('未找到匹配的修复预案')
    }
  }

  const handleExecutePlan = async (dryRun: boolean = true) => {
    if (!selectedPlan || !selectedAlert) return

    const stepIndices = selectedPlan.steps?.map((_, idx) => idx) || []
    try {
      setExecutingSteps(stepIndices)
      setExecuteResults([])

      if (dryRun) {
        // 预演模式
        const result = await executePlan(selectedPlan.plan_id, stepIndices, true)
        setExecuteResults([{ step: 0, name: '预演模式', output: JSON.stringify(result, null, 2) }])
        setShowExecuteDrawer(true)
        message.info('预演完成，未实际执行任何操作')
      } else {
        // 实际执行
        const result = await executePlan(selectedPlan.plan_id, stepIndices, false)
        setExecuteResults(result.results || [])
        setShowExecuteDrawer(true)
        message.success('预案执行完成')
      }
    } catch (error) {
      message.error('执行预案失败')
    } finally {
      setExecutingSteps([])
    }
  }

  const columns = [
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      render: (level: string) => (
        <Tag color={level === 'critical' ? 'red' : 'orange'}>
          <WarningOutlined /> {level === 'critical' ? '严重' : '警告'}
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
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const statusMap: Record<string, { color: string; text: string }> = {
          active: { color: 'red', text: '活跃' },
          acknowledged: { color: 'blue', text: '已确认' },
          resolved: { color: 'green', text: '已解决' },
        }
        const s = statusMap[status] || { color: 'default', text: status }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Alert) => (
        <Space size="small">
          {record.status === 'active' && (
            <>
              <Button
                size="small"
                icon={<CheckOutlined />}
                onClick={() => handleAcknowledge(record.id)}
              >
                确认
              </Button>
              <Button
                size="small"
                icon={<CloseOutlined />}
                onClick={() => handleResolve(record.id)}
              >
                解决
              </Button>
            </>
          )}
          <Button
            size="small"
            icon={<ToolOutlined />}
            onClick={() => showRemediation(record)}
          >
            预案
          </Button>
        </Space>
      ),
    },
  ]

  const planSteps: StepProps[] = selectedPlan?.steps?.map((step, idx) => ({
    key: idx,
    title: step.name,
    description: step.description,
    status: executeResults.find(r => r.step === idx + 1)?.success ? 'finish' :
            executeResults.find(r => r.step === idx + 1)?.error ? 'error' : 'wait',
  })) || []

  return (
    <>
      <Card
        title="告警管理"
        className="alert-panel"
        style={{ margin: 24 }}
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadAlerts} loading={alertsLoading}>
            刷新
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={alerts}
          loading={alertsLoading}
          rowKey="id"
          pagination={{ pageSize: 10 }}
          scroll={{ x: 800 }}
        />
      </Card>

      {/* 预案 Modal */}
      <Modal
        title="修复预案"
        open={showPlanModal}
        onCancel={() => setShowPlanModal(false)}
        footer={null}
        width={700}
      >
        {selectedPlan && (
          <div>
            <Typography.Paragraph>
              <strong>预案名称:</strong> {selectedPlan.name}
            </Typography.Paragraph>
            <Typography.Paragraph>
              <strong>描述:</strong> {selectedPlan.description}
            </Typography.Paragraph>
            <Typography.Paragraph>
              <strong>风险等级:</strong>
              <Tag color={selectedPlan.risk_level === 'high' ? 'red' :
                        selectedPlan.risk_level === 'medium' ? 'orange' : 'green'}>
                {selectedPlan.risk_level === 'high' ? '高' :
                 selectedPlan.risk_level === 'medium' ? '中' : '低'}
              </Tag>
            </Typography.Paragraph>

            {selectedPlan.steps && (
              <div style={{ marginTop: 16 }}>
                <strong>执行步骤:</strong>
                <Table
                  columns={[
                    { title: '步骤', dataIndex: 'order', key: 'order', width: 60 },
                    { title: '名称', dataIndex: 'name', key: 'name' },
                    { title: '描述', dataIndex: 'description', key: 'description' },
                    { title: '风险', dataIndex: 'risk', key: 'risk',
                      render: (risk: string) => (
                        <Tag color={risk === 'high' ? 'red' : risk === 'medium' ? 'orange' : 'green'}>
                          {risk === 'high' ? '高' : risk === 'medium' ? '中' : '低'}
                        </Tag>
                      )
                    },
                  ]}
                  dataSource={selectedPlan.steps.map((s, i) => ({ ...s, key: i }))}
                  pagination={false}
                  size="small"
                />
              </div>
            )}

            <Space style={{ marginTop: 16 }}>
              <Button
                type="primary"
                icon={<ToolOutlined />}
                onClick={() => handleExecutePlan(false)}
              >
                执行预案
              </Button>
              <Button
                onClick={() => handleExecutePlan(true)}
              >
                预演
              </Button>
              <Button
                icon={<CloseOutlined />}
                onClick={() => setShowPlanModal(false)}
              >
                关闭
              </Button>
            </Space>
          </div>
        )}
      </Modal>

      {/* 执行结果 Drawer */}
      <Drawer
        title="预案执行结果"
        placement="right"
        width={600}
        open={showExecuteDrawer}
        onClose={() => {
          setShowExecuteDrawer(false)
          setExecuteResults([])
        }}
      >
        {executeResults.length > 0 ? (
          <Steps
            direction="vertical"
            items={planSteps}
            current={executeResults.length}
          />
        ) : (
          <Typography.Text>暂无执行结果</Typography.Text>
        )}
      </Drawer>
    </>
  )
}
