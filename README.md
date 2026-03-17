# opsMind

基于 FastAPI 与 React 的运维分析平台，用于统一查看流量、资源、异常、建议和任务追踪。

简体中文 | [English](README_EN.md)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19+-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)

## Features

- 统一总览大盘，展示关键状态、热点服务和近期异常
- 流量分析，支持请求趋势、状态码、路径、来源 IP、UA 和错误样本
- 资源分析，支持主机、容器、Pod、服务维度的热点与风险展示
- 异常中心，支持 incident 列表、证据链、摘要与分析入口
- 建议中心，支持 baseline / recommended / diff 三视图、YAML 预览、复制、导出与反馈
- 任务中心，支持任务状态、阶段、trace、artifact 与失败诊断
- AI 助手与 Metrics 面板，支持模型调用状态、诊断问答和质量指标
- 只读执行插件，支持 Linux、Docker、Kubernetes 诊断命令

## Architecture

```text
logs / metrics / assets
  -> traffic / resource analytics
  -> incidents
  -> recommendations
  -> tasks / traces / artifacts
  -> ai assistant / quality metrics
```

详细模块说明见 [docs/architecture.md](docs/architecture.md)，推荐阅读顺序见 [docs/docs-index.md](docs/docs-index.md)。

## Tech Stack

### Backend

- Python 3.10+
- FastAPI
- SQLite
- 自定义任务运行时

### Frontend

- React 19
- TypeScript
- Vite
- Ant Design 5
- Zustand

## Project Structure

```text
opsMind/
├─ api/                  # 路由、依赖注入、WebSocket
├─ engine/
│  ├─ analytics/         # 流量、资源、关联分析
│  ├─ domain/            # 资产、信号、异常、建议服务
│  ├─ ingest/            # 日志解析与聚合
│  ├─ llm/               # AI Provider 与路由
│  ├─ operations/        # 执行插件与运维操作
│  ├─ runtime/           # 任务、状态机、trace、artifact
│  └─ storage/           # SQLite 与仓储层
├─ frontend/             # React 前端
├─ scripts/              # 演示数据与辅助脚本
├─ data/                 # 本地运行数据
└─ docs/                 # 项目文档
```

## Documentation

- [Documentation Index](docs/docs-index.md)
- [English README](README_EN.md)
- [Architecture](docs/architecture.md)
- [Architecture (EN)](docs/architecture.en.md)
- [API Overview](docs/api-overview.md)
- [Deployment Guide](docs/deployment.md)
- [Project Scope](docs/project-scope.md)
- [Project Scope (EN)](docs/project-scope.en.md)
- [Demo Scenarios](docs/demo-scenarios.md)
- [Verification Matrix](docs/verification.md)
- [Release Guide](docs/release.md)
- [Changelog](CHANGELOG.md)

## Community

- 贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)
- 社区协作规范见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全问题披露见 [SECURITY.md](SECURITY.md)
- 默认模块归属见 [.github/CODEOWNERS](.github/CODEOWNERS)

## Quick Start

### Requirements

- Python 3.10+
- Node.js 18+
- Docker（可选）
- Prometheus（可选）

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- 详细部署说明见 [docs/deployment.md](docs/deployment.md)

### Local Development

后端：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

前端：

```bash
cd frontend
npm install
npm run dev
```

更完整的部署与运行方式见 [docs/deployment.md](docs/deployment.md)。

## Configuration

环境变量示例见 `.env.example`。

常用配置：

- `BACKEND_PORT`：后端端口，默认 `8000`
- `FRONTEND_PORT`：前端端口，默认 `3000`
- `DATA_SOURCES`：数据源类型，默认 `logfile`
- `ACCESS_LOG_PATHS`：访问日志路径
- `ENABLE_SEED`：是否执行演示数据初始化脚本
- `SEED_RESET`：是否重置演示数据脚本生成的固定样本
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`：AI Provider 配置
- `PROMETHEUS_URL`：Prometheus 地址
- `DOCKER_HOST`：Docker Socket 或管道地址

## Demo Data

项目内置了演示数据脚本：

```bash
python scripts/seed_demo_data.py
python scripts/verify_demo_data.py
python scripts/demo_doctor.py --seed --write-report
```

- `seed_demo_data.py`：初始化日志、异常、建议、任务和 artifact
- `verify_demo_data.py`：检查演示数据、场景覆盖和三视图产物是否完整
- `demo_doctor.py`：输出演示环境报告、推荐讲解顺序和缺失项，并写入 `data/demo/demo_report.json`

推荐演示路径见 [docs/demo-scenarios.md](docs/demo-scenarios.md)。

## API

详细接口总览见 [docs/api-overview.md](docs/api-overview.md)。

主产品接口：

- `/api/dashboard/*`
- `/api/traffic/*`
- `/api/resources/*`
- `/api/incidents/*`
- `/api/recommendations/*`
- `/api/tasks/*`
- `/api/metrics/*`
- `/api/executors/*`
- `/api/ai/*`

调试接口：

- `api/legacy_routes.py`

说明：调试接口主要服务于开发辅助页，不建议作为外部系统的长期集成入口。

## Development

前端构建：

```bash
cd frontend
npm run build
```

## Contributing

欢迎通过 Issue 和 Pull Request 参与改进。详细协作流程、模块归属和提交期望见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

Apache 2.0
