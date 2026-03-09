# opsMind

**智能运维助手** - 可控、可追溯的运维诊断与告警管理

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19+-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)

## 项目定位

opsMind 是一个独立设计的 AIOps 开源项目，提供：

- **主机资源监控** - CPU、内存、磁盘、网络实时监控
- **告警管理** - 告警规则创建、查询、确认、解决
- **修复预案** - 故障自动修复方案推荐和执行
- **容器诊断** - Docker 容器状态检查、日志获取
- **K8s YAML 生成** - Kubernetes 配置文件自动生成
- **日志分析** - 日志文件错误模式识别
- **WebSocket 实时推送** - 告警实时通知

## 核心功能

### 1. 主机资源监控

实时监控服务器资源状态，自动检测异常并生成告警：

| 监控指标 | 说明 | 告警阈值 |
|---------|------|---------|
| CPU 使用率 | 实时 CPU 占用百分比 | >70% 警告，>90% 严重 |
| 内存使用率 | 实时内存占用百分比 | >70% 警告，>90% 严重 |
| 磁盘使用率 | 各分区磁盘使用情况 | >70% 警告，>90% 严重 |
| 网络流量 | 发送/接收数据量 | - |

### 2. 告警管理

完整的告警生命周期管理：

```
主动告警 → 告警确认 → 预案推荐 → 执行修复 → 告警解决
```

- **告警规则**：支持灵活配置监控指标、阈值、严重程度
- **告警查询**：按状态、严重程度筛选告警
- **告警确认**：手动确认告警，标记已处理
- **告警解决**：问题解决后关闭告警

### 3. 智能根因分析

采用混合分析模式的智能根因分析器：

| 分析模式 | 说明 | 适用场景 |
|---------|------|---------|
| **规则模式** | 基于预定义规则库快速分析 | 常见告警类型（CPU、内存、磁盘、容器崩溃等） |
| **LLM 模式** | 调用大语言模型深度分析 | 未知告警、复杂场景、需要详细解释 |

- 支持多 LLM Provider 配置（OpenAI、Anthropic、自定义 API）
- 自动故障转移，确保服务可用性
- LLM 不可用时自动降级到规则模式
- 提供详细的可能原因、建议操作和诊断命令

**支持的 LLM Provider**:
- OpenAI (GPT-4o, GPT-3.5-Turbo)
- Anthropic (Claude Sonnet, Claude Opus)
- 自定义 OpenAI 兼容 API

### 4. 修复预案

内置常见故障的修复预案：

| 预案名称 | 触发条件 | 修复步骤 | 风险等级 |
|---------|---------|---------|---------|
| CPU 过高 | CPU 使用率 >80% | 1. 识别高负载进程<br>2. 检查异常进程<br>3. 重启异常服务<br>4. 扩容 | 中 |
| 内存过高 | 内存使用率 >85% | 1. 识别内存占用进程<br>2. 清理系统缓存<br>3. 重启泄漏服务 | 低 |
| 磁盘满 | 磁盘使用率 >85% | 1. 分析磁盘使用<br>2. 清理日志文件<br>3. 清理临时文件<br>4. 扩容磁盘 | 中 |
| 容器崩溃 | 容器状态=exited | 1. 查看容器日志<br>2. 检查容器状态<br>3. 重启容器 | 低 |

### 5. 容器诊断

Docker 容器管理能力：

- 容器列表查询（运行中/已停止）
- 容器详细信息查看
- 容器日志获取
- 容器健康诊断

### 6. 系统诊断

一键获取系统详细状态：

- 主机资源使用情况
- Docker 服务状态
- 告警系统状态
- 容器数量统计

### 7. 日志分析

日志文件分析和错误识别：

- 支持日志文件读取和级别过滤
- 自动识别错误模式（异常、超时、内存、连接等）
- 日志统计信息（级别分布、错误率）
- 日志目录扫描

### 8. K8s YAML 生成

Kubernetes 配置文件自动生成：

- **Deployment** - 自动生成副本、资源限制、环境变量配置
- **Service** - 生成 ClusterIP/NodePort/LoadBalancer 类型服务
- **ConfigMap** - 生成配置字典
- **Ingress** - 生成 ingress 配置（支持 TLS）

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+ (前端)
- Docker（可选，用于容器诊断功能）

### 后端安装

1. **克隆项目**

```bash
git clone <repository-url>
cd opsMind
```

2. **创建虚拟环境**

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

3. **安装依赖**

```bash
pip install -r requirements.txt
```

4. **配置环境变量**

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入 LLM API Key
# LLM_API_KEY=your_api_key_here
```

5. **启动服务**

```bash
python main.py
```

服务将在 `http://localhost:8000` 启动。

### 前端安装

1. **进入前端目录**

```bash
cd frontend
```

2. **安装依赖**

```bash
npm install
```

3. **启动开发服务器**

```bash
npm run dev
```

前端将在 `http://localhost:3000` 启动，自动代理后端 API 请求。

### 验证安装

```bash
# 健康检查
curl http://localhost:8000/health

# 查看可用能力
curl http://localhost:8000/api/capabilities

# 主机监控
curl http://localhost:8000/api/host/metrics
```

## 前端界面

opsMind 提供现代化的 Web 界面，基于 React 19 + TypeScript + Ant Design 5 构建：

### 监控仪表盘

- 实时资源监控卡片（CPU/内存/磁盘/网络）
- 告警信息展示
- WebSocket 实时连接状态
- 一键刷新数据

### 告警管理

- 告警列表（支持状态筛选）
- 告警确认/解决操作
- 修复预案推荐
- 预案执行（预演/实际执行）

### 告警规则

- 规则列表展示
- 新建/编辑/删除规则
- 规则启用/禁用

### 容器管理

- 容器列表（支持全量/运行中）
- 容器详情查看
- 容器日志获取
- 容器健康诊断

### 系统设置

- 系统健康状态
- 系统版本信息
- 能力数量统计
- 资源使用详情
- 服务状态监控

### LLM 配置（新增）

- Provider 列表管理（OpenAI、Anthropic、自定义）
- 添加/编辑/删除 Provider
- 连接测试
- 默认 Provider 设置

## API 端点参考

### REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/capabilities` | GET | 获取能力列表 |
| `/api/capabilities/{name}/dispatch` | POST | 调用能力 |
| `/api/alerts` | GET | 查询告警列表 |
| `/api/alerts/acknowledge` | POST | 确认告警 |
| `/api/alerts/resolve` | POST | 解决告警 |
| `/api/alerts/rules` | GET | 获取告警规则列表 |
| `/api/alerts/rules` | POST | 创建告警规则 |
| `/api/alerts/rules/{rule_id}` | DELETE | 删除告警规则 |
| `/api/remediation/plans` | GET | 获取修复预案列表 |
| `/api/remediation/plans/{plan_id}` | GET | 获取预案详情 |
| `/api/remediation/execute` | POST | 执行修复预案 |
| `/api/containers` | GET | 获取容器列表 |
| `/api/containers/{name}` | GET | 获取容器详情 |
| `/api/containers/{name}/logs` | GET | 获取容器日志 |
| `/api/host/metrics` | GET | 获取主机监控指标 |
| `/api/diagnose` | GET | 系统诊断信息 |

### WebSocket

| 端点 | 说明 |
|------|------|
| `/ws/{client_id}` | 告警实时推送 |

## API 使用示例

### 主机资源监控

```bash
# 使用能力调用接口
curl -X POST http://localhost:8000/api/capabilities/inspect_host/dispatch \
  -H "Content-Type: application/json" \
  -d '{"metrics": ["cpu", "memory", "disk"]}'

# 或直接使用诊断端点
curl http://localhost:8000/api/diagnose
```

**响应示例：**
```json
{
  "system": {
    "cpu_usage": 45.2,
    "memory_usage": 62.8,
    "memory_available_mb": 8192.5,
    "disk_usage": 55.0,
    "disk_free_gb": 256.8
  },
  "services": {
    "docker": {
      "status": "available",
      "containers": 5
    },
    "alerts": {
      "active": 2,
      "rules": 4
    }
  }
}
```

### 创建告警规则

```bash
curl -X POST http://localhost:8000/api/alerts/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CPU 过高告警",
    "metric": "cpu_usage",
    "threshold": 80,
    "operator": ">",
    "severity": "warning"
  }'
```

### 查询活动告警

```bash
curl http://localhost:8000/api/alerts?status=active&limit=10
```

### 获取修复预案

```bash
curl http://localhost:8000/api/remediation/plans/cpu_high
```

### 执行修复预案

```bash
# 预演模式
curl -X POST "http://localhost:8000/api/remediation/execute?plan_id=cpu_high&step_indices=0,1,2&dry_run=true"

# 实际执行
curl -X POST "http://localhost:8000/api/remediation/execute?plan_id=cpu_high&step_indices=0,1,2&dry_run=false"
```

## 项目结构

```
opsMind/
├── main.py                     # FastAPI 入口
├── settings.py                 # 配置管理
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── .gitignore                  # Git 忽略文件
├── README.md                   # 项目文档
│
├── engine/
│   ├── contracts.py            # 数据模型定义
│   ├── capabilities/
│   │   ├── base.py             # 能力基类
│   │   ├── decorators.py       # 装饰器（超时/错误处理）
│   │   ├── host_monitor.py     # 主机监控
│   │   ├── container_inspector.py  # 容器诊断
│   │   ├── log_analyzer.py     # 日志分析
│   │   ├── k8s_yaml_generator.py  # K8s YAML 生成
│   │   ├── alert_manager.py    # 告警管理
│   │   ├── remediation.py      # 修复预案库
│   │   └── execute_remediation.py  # 执行修复
│   ├── storage/
│   │   └── alert_store.py      # 告警存储（JSON 文件）
│   └── integrations/
│       └── data_sources/       # 数据源适配器
│
├── api/
│   └── routes.py               # REST API 路由
│
└── frontend/                   # React + TypeScript 前端
    ├── src/
    │   ├── App.tsx             # 主应用
    │   ├── main.tsx            # 入口文件
    │   ├── index.css           # 全局样式（含响应式）
    │   ├── api/
    │   │   └── client.ts       # API 客户端（含错误拦截）
    │   ├── utils/
    │   │   └── errorHandler.ts # 错误处理工具
    │   ├── stores/             # Zustand 状态管理
    │   │   ├── alertStore.ts   # 告警状态
    │   │   └── monitorStore.ts # 监控状态
    │   ├── hooks/
    │   │   └── useAlertWebSocket.ts # WebSocket Hook
    │   └── components/         # React 组件
    │       ├── Dashboard/      # 监控仪表盘
    │       ├── AlertPanel/     # 告警管理
    │       ├── AlertRules/     # 告警规则
    │       ├── ContainerList/  # 容器管理
    │       ├── SystemSettings/ # 系统设置
    │       └── ErrorBoundary/  # 错误边界
    └── package.json
```

## 架构设计

### 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        前端界面 (React)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ Dashboard│ │AlertPanel│ │Container │ │SystemSettings│   │
│  │ 仪表盘   │ │ 告警管理 │ │ 容器管理 │ │   系统设置   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
│         │              │              │              │       │
│         └──────────────┴──────────────┴──────────────┘       │
│                              │                                │
│                    ┌─────────▼─────────┐                     │
│                    │   API Client      │                     │
│                    │  (错误拦截/重试)   │                     │
│                    └─────────┬─────────┘                     │
└──────────────────────────────┼───────────────────────────────┘
                               │ HTTP/WebSocket
┌──────────────────────────────▼───────────────────────────────┐
│                      FastAPI 后端                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   API Routes                        │   │
│  │  /api/capabilities | /api/alerts | /api/containers  │   │
│  └──────────────────────────────────────────────────────┘   │
│         │              │              │              │        │
│  ┌──────▼──────┐ ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼──────┐ │
│  │HostMonitor  │ │AlertManager│ │Remediation│ │Container   │ │
│  │主机监控     │ │告警管理    │ │修复预案   │ │Inspector   │ │
│  └─────────────┘ └───────────┘ └───────────┘ └────────────┘ │
│         │              │              │              │        │
│  ┌──────▼──────────────▼──────────────▼──────────────▼──────┐│
│  │                    AlertStore                            ││
│  │              (告警规则 + 告警历史)                          ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

### 告警工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    告警处理流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 监控采集 → HostMonitor.inspect_host()                       │
│       ↓                                                         │
│  2. 阈值检测 → AlertStore.create_alert()                        │
│       ↓                                                         │
│  3. 告警展示 → AlertPanel (前端轮询/WS 推送)                       │
│       ↓                                                         │
│  4. 预案推荐 → RemediationPlan.dispatch()                       │
│       ↓                                                         │
│  5. HITL 确认 → 用户确认执行修复                                  │
│       ↓                                                         │
│  6. 执行修复 → ExecuteRemediation.dispatch()                    │
│       ↓                                                         │
│  7. 告警解决 → AlertStore.resolve_alert()                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 技术栈

### 后端
- **Python 3.10+** - 主要编程语言
- **FastAPI** - 高性能 Web 框架
- **Pydantic** - 数据验证
- **psutil** - 系统资源监控
- **Docker SDK** - 容器管理
- **uvicorn** - ASGI 服务器

### 前端
- **React 19** - UI 框架
- **TypeScript 5** - 类型系统
- **Ant Design 5** - UI 组件库
- **Zustand** - 状态管理
- **React Router v7** - 路由管理
- **Axios** - HTTP 客户端

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值                           |
|-------|------|-------------------------------|
| `LLM_API_KEY` | LLM API 密钥（必填） | -                             |
| `LLM_BASE_URL` | LLM API 地址 | `https://api.openai.com/v1`   |
| `LLM_MODEL` | 模型名称 | `gpt-5`                       |
| `PORT` | 服务端口 | `8000`                        |
| `DEBUG` | 调试模式 | `false`                       |
| `DOCKER_HOST` | Docker 守护进程地址 | `unix:///var/run/docker.sock` |

## 常见问题

### Q: Docker 服务不可用怎么办？
A: opsMind 的容器诊断功能需要 Docker 服务。如果你没有安装 Docker，该功能将自动禁用，但不影响其他功能的使用。

### Q: 告警规则不生效？
A: 请检查：
1. 规则是否已启用（enabled=true）
2. 阈值条件是否合理
3. 监控数据采集是否正常

### Q: WebSocket 连接失败？
A: WebSocket 用于实时告警推送，连接失败不影响核心功能。前端会自动降级为轮询模式。

### Q: 如何贡献代码？
A: 欢迎提交 PR！请先 fork 项目，开发完成后提交 pull request。

## 相关链接

- [项目计划文档](https://github.com/xxx/opsMind/blob/main/PLAN.md)
- [API 文档](https://github.com/xxx/opsMind/blob/main/docs/API.md)
- [问题反馈](https://github.com/xxx/opsMind/issues)

## License

Apache 2.0
