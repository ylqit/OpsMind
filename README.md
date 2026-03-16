# opsMind

基于 FastAPI 和 React 的运维分析平台，面向日志、资源、异常、建议和任务追踪的统一工作台。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19+-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)

## 项目定位

opsMind 当前围绕以下主链路建设：

```text
日志 / 指标 / 资产接入
  -> 流量与资源分析
  -> Incident 分析
  -> Recommendation 草稿与 diff
  -> Task / Trace / Artifact 追踪
  -> 审批与反馈
```

当前版本重点在于把运维分析、建议生成和任务追踪放在同一套产品界面中，先把可观测、可追溯、可交付做扎实。

## 当前功能

- 总览大盘：展示关键状态、热点服务和近期异常摘要
- 流量分析：按时间窗和服务维度查看请求趋势、状态码、路径、来源 IP、UA 和错误样本
- 资源分析：按主机、容器、Pod、服务维度汇总资源热点、OOM 和重启风险
- 异常中心：查看 incident 列表、证据链、日志样本、分析摘要和建议入口
- 建议中心：查看 recommendation、基线 / 建议 / diff 三视图、YAML 复制与下载、审批与反馈
- 任务中心：跟踪任务状态、阶段、trace 和 artifact
- 质量看板：查看建议采纳率、任务成功率、AI 调用质量和成本指标
- 执行插件：提供只读优先的 Linux、Docker、Kubernetes 诊断能力
- 能力调试：保留旧能力接口的调试入口，不作为主产品路径

## 技术栈

### 后端

- Python 3.10+
- FastAPI
- SQLite
- 自定义任务运行时

### 前端

- React 19
- TypeScript
- Vite
- Ant Design 5
- Zustand

## 目录说明

- `api/routes/`：主产品聚合路由
- `api/legacy_routes.py`：旧能力调试路由
- `api/websocket.py`：WebSocket 事件推送
- `engine/runtime/`：任务、状态机、trace、artifact、事件总线
- `engine/domain/`：Asset、Signal、Incident、Recommendation 服务
- `engine/analytics/`：流量、资源、关联分析
- `engine/ingest/`：日志解析与聚合
- `engine/operations/`：执行插件与运维操作
- `engine/storage/`：SQLite 与仓储层
- `frontend/src/pages/`：总览、流量、资源、异常、建议、任务、质量、执行插件页面
- `frontend/src/stores/`：前端状态
- `data/`：任务产物、日志与运行数据
- `tests/`：后端测试

## 接口分层

### 主产品路由

前端主页面统一使用以下聚合接口：

- `/api/dashboard/*`
- `/api/traffic/*`
- `/api/resources/*`
- `/api/incidents/*`
- `/api/recommendations/*`
- `/api/tasks/*`
- `/api/metrics/*`
- `/api/executors/*`
- `/api/ai/*`

### 调试路由

- `api/legacy_routes.py`

这部分只保留旧能力接口和调试用途，不承载主导航页面。

## 运行时内核

`engine/runtime/` 负责以下能力：

- `task_manager.py`：任务创建、推进、失败收敛
- `state_machine.py`：任务状态流转约束
- `trace_store.py`：步骤、动作、观察记录
- `artifact_store.py`：大结果外置到文件系统
- `event_bus.py`：任务和事件推送

## 前端页面

当前主导航包含以下页面：

- `OverviewDashboard`
- `TrafficAnalytics`
- `ResourceAnalytics`
- `IncidentCenter`
- `RecommendationCenter`
- `TaskCenter`
- `QualityMetrics`
- `AIAssistantWorkbench`
- `ExecutorPlugins`
- `CapabilityWorkbench`
- `LLMSettings`

其中流量、资源、异常、质量等页面已经开始通过 `frontend/src/stores/workspaceFilterStore.ts` 共享时间窗和服务筛选上下文。

## 快速启动

### 环境要求

- Python 3.10+
- Node.js 18+
- 可选：Docker
- 可选：Prometheus

### Docker Compose 启动

```bash
cp .env.example .env
docker compose up -d --build
```

默认地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

说明：

- SQLite 文件位于容器内 `/app/data/opsmind.db`，由 compose volume 持久化。
- 首次启动会自动执行 `scripts/seed_demo_data.py`，写入演示日志、incident、recommendation、task 和 artifact。
- 如需每次启动重置演示数据，可在 `.env` 中将 `SEED_RESET=true`。
- 当 Docker/Prometheus 未接入时，资源分析页会自动回退到 seed 样本，保证演示环境可完整展示热点、风险和容器摘要。

### 后端启动

```bash
git clone <repository-url>
cd opsMind
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

默认地址：

- 后端：`http://localhost:8000`

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

默认地址：

- 前端：`http://localhost:3000`

## 常用接口

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/dashboard/overview
curl "http://localhost:8000/api/traffic/summary?time_range=1h"
curl "http://localhost:8000/api/resources/summary?time_range=1h"
curl http://localhost:8000/api/incidents
curl http://localhost:8000/api/tasks
```

## 开发约定

- 主导航页面优先使用 `api/routes/` 下的聚合路由
- 新的 AI 能力优先落在 `/api/ai/*`
- 执行插件默认保持只读优先
- YAML 草稿、diff 和大结果通过任务与 artifact 交付

## License

Apache 2.0
