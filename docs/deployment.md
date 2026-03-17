# Deployment Guide

本文档整理 `opsMind` 的部署与运行方式，适用于本地开发、Docker Compose 演示环境，以及面向自托管场景的最小生产部署。

## Deployment Modes

当前仓库推荐以下三种模式：

- 本地开发模式：适合功能开发与页面联调
- Docker Compose 模式：适合快速体验和演示
- 自托管模式：适合在受控环境中长期运行

## Requirements

### Common

- Python 3.10+
- Node.js 18+
- Git

### Optional Integrations

- Docker
- Prometheus
- AI Provider compatible endpoint

## Environment Configuration

复制环境变量模板：

```bash
cp .env.example .env
```

常用配置项：

- `BACKEND_PORT`：后端端口，默认 `8000`
- `FRONTEND_PORT`：前端端口，默认 `3000`
- `DATA_SOURCES`：数据源类型，默认 `logfile`
- `ACCESS_LOG_PATHS`：访问日志路径
- `ENABLE_SEED`：是否自动补齐演示数据
- `SEED_RESET`：是否重置固定演示样本
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`：AI Provider 配置
- `PROMETHEUS_URL`：Prometheus 地址
- `DOCKER_HOST`：Docker Socket 或管道地址

## Docker Compose

当前仓库提供最小 Compose 方案：

```bash
cp .env.example .env
docker compose up -d --build
```

默认端口：

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

说明：

- Compose 默认以 `logfile` 模式启动，避免未挂载 Docker Socket 时后端直接失败
- 默认会使用演示数据入口，适合初次体验和功能讲解
- SQLite 数据和日志目录由 Compose volume 承载

## Local Development

### Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Frontend Build Check

```bash
cd frontend
npm run build
```

## Demo Mode

如果你希望在没有真实 Prometheus 或 Docker 数据源的情况下体验主链路，推荐开启演示模式：

```bash
python scripts/seed_demo_data.py
python scripts/verify_demo_data.py
python scripts/demo_doctor.py --seed --write-report
```

适用场景：

- 首次体验仓库
- 演示异常、建议、任务、AI 助手闭环
- 验证文档和页面主流程是否对齐

## Self-hosted Notes

如果用于自托管环境，建议注意以下事项：

- 不要把 `.env`、真实 API Key 或敏感连接信息提交到版本库
- 如开启 AI Provider，请确认 `LLM_BASE_URL`、模型名和密钥配置正确
- 如果启用 Docker 数据源，请确认运行环境允许访问 Docker Socket 或命名管道
- 如果启用 Prometheus，请确认网络访问与鉴权策略符合部署环境要求
- 执行插件默认应保持只读，不建议引入默认开启的写操作命令

## Data And Persistence

当前持久化策略分为两层：

- SQLite：结构化主数据
- 文件系统：trace、artifact、草稿与报告内容

部署时建议重点关注：

- `data/` 的持久化
- 日志输入目录是否可读
- 产物目录是否可写

## Production-oriented Recommendations

如果你准备长期运行 `opsMind`，建议至少补齐以下保护措施：

- 在反向代理或网关后暴露后端
- 限制执行插件的可用环境
- 定期备份 SQLite 与关键产物目录
- 明确日志源与监控源的权限边界
- 将 AI Provider 密钥保存在受控环境变量或密钥管理系统中

## Related Documents

- [Architecture](./architecture.md)
- [Demo Scenarios](./demo-scenarios.md)
- [Release Guide](./release.md)
- [Security](../SECURITY.md)
