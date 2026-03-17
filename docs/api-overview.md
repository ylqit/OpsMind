# API Overview

本文档概览 `opsMind` 当前对外公开的主产品接口，帮助读者快速理解路由边界、典型用途和调试接口范围。

## API Scope

主产品接口集中在 [api/routes](../api/routes)，通过统一聚合路由对外暴露。

核心入口包括：

- `/api/dashboard/*`
- `/api/reports/*`
- `/api/traffic/*`
- `/api/resources/*`
- `/api/incidents/*`
- `/api/recommendations/*`
- `/api/tasks/*`
- `/api/metrics/*`
- `/api/executors/*`
- `/api/ai/*`

调试接口单独保留在 [api/legacy_routes.py](../api/legacy_routes.py)，不属于主产品 API 面。

## Common Request Context

多个主产品接口会共享以下上下文参数：

- `time_range`：时间窗，常见值如 `1h`、`6h`、`24h`
- `service_key`：服务维度过滤
- `task_id`：与任务中心关联的运行上下文
- `incident_id` / `recommendation_id`：异常与建议的关联对象

这些参数贯穿总览、流量、资源、异常、建议、任务和 AI 助手主链路。

## Route Groups

### Dashboard

前缀：

- `/api/dashboard`
- `/api/reports`

代表性接口：

- `GET /api/dashboard/overview`
- `POST /api/reports/daily`

主要用途：

- 聚合流量、资源、异常与数据源状态，输出主控台总览
- 生成日报任务与报表产物

### Traffic

前缀：

- `/api/traffic`

代表性接口：

- `GET /api/traffic/summary`

主要用途：

- 返回请求趋势、状态码、路径、来源 IP、UA 和错误样本等流量分析结果

### Resources

前缀：

- `/api/resources`
- `/api/assets`

代表性接口：

- `GET /api/resources/summary`
- `GET /api/assets`

主要用途：

- 返回资源热点、风险摘要和资产列表
- 支持按服务、资产类型、健康状态筛选

### Incidents

前缀：

- `/api/incidents`

代表性接口：

- `GET /api/incidents`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/ai-summary`
- `POST /api/incidents/analyze`

主要用途：

- 列出异常
- 查看异常详情、证据链、诊断结论和基线偏移信息
- 触发 AI 总结
- 从当前现场生成新的异常分析任务

### Recommendations

前缀：

- `/api/recommendations`

代表性接口：

- `POST /api/recommendations/generate`
- `GET /api/recommendations/{recommendation_id}`
- `GET /api/recommendations/{recommendation_id}/feedback`
- `POST /api/recommendations/{recommendation_id}/feedback`
- `POST /api/recommendations/{recommendation_id}/ai-review`

主要用途：

- 从异常生成建议
- 查看建议详情、三视图、证据与诊断报告
- 提交采纳、拒绝或改写反馈
- 触发 AI 复核

### Tasks

前缀：

- `/api/tasks`

代表性接口：

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/diagnosis`
- `GET /api/tasks/{task_id}/artifacts`
- `GET /api/tasks/{task_id}/artifacts/{artifact_id}/content`
- `POST /api/tasks/{task_id}/approve`
- `POST /api/tasks/{task_id}/cancel`

主要用途：

- 查看任务状态、阶段、失败诊断
- 查看 artifact、trace 与诊断时间轴
- 对需要人工确认的任务执行审批

### Metrics

前缀：

- `/api/metrics`

代表性接口：

- `GET /api/metrics/recommendation`
- `GET /api/metrics/ai-usage`

主要用途：

- 查看建议质量相关指标
- 查看 AI 调用、使用量和成本相关指标

### Executors

前缀：

- `/api/executors`

代表性接口：

- `GET /api/executors/status`
- `GET /api/executors/readonly-command-packs`
- `GET /api/executors/recommended-command-packs`
- `POST /api/executors/run`
- `GET /api/executors/executions/{execution_id}`
- `PATCH /api/executors/plugins/{plugin_key}`

主要用途：

- 查看执行插件状态
- 获取只读命令包与基于上下文的推荐命令包
- 执行只读补证命令并读取执行记录
- 调整插件启用状态

### AI

前缀：

- `/api/ai`

代表性接口：

- `GET /api/ai/assistant/status`
- `POST /api/ai/assistant/diagnose`
- `POST /api/ai/assistant/sessions`
- `GET /api/ai/assistant/sessions/{session_id}`
- `PATCH /api/ai/assistant/sessions/{session_id}`
- `POST /api/ai/assistant/writebacks`
- `POST /api/ai/chat`
- `GET /api/ai/providers`
- `POST /api/ai/providers`
- `POST /api/ai/providers/test`
- `PATCH /api/ai/providers/{provider_id}`
- `DELETE /api/ai/providers/{provider_id}`
- `GET /api/ai/call-logs`

主要用途：

- 管理 AI 助手分析会话
- 发起诊断请求与保存 AI 回写
- 管理 Provider、连通性检测与调用日志

## Debug-only APIs

调试接口位于 [api/legacy_routes.py](../api/legacy_routes.py)，当前只保留：

- `GET /capabilities`
- `POST /capabilities/{name}/dispatch`

说明：

- 这组接口主要服务于能力调试工作台
- 不建议将其视为主产品集成入口
- 不建议将其视为稳定版本化契约

## Integration Guidance

如果你是新接入方，建议优先按以下顺序理解接口：

1. `dashboard / traffic / resources`
2. `incidents / recommendations`
3. `tasks`
4. `ai`
5. `executors`

如果你的目标是接主产品链路，优先依赖聚合接口，不建议直接耦合到内部运行时或调试层接口。

## Related Documents

- [Architecture](./architecture.md)
- [Deployment Guide](./deployment.md)
- [Demo Scenarios](./demo-scenarios.md)
- [Release Guide](./release.md)
