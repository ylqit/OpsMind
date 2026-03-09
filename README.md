# opsMind

**智能运维助手** - 可控、可追溯的运维诊断与告警管理

## 项目定位

opsMind 是一个独立设计的 AIOps 开源项目，提供：

- **主机资源监控** - CPU、内存、磁盘、网络实时监控
- **告警管理** - 告警规则创建、查询、确认、解决
- **修复预案** - 故障自动修复方案推荐
- **容器诊断** - Docker 容器状态检查（后续支持）
- **K8s YAML 生成** - Kubernetes 配置文件生成（后续支持）

## 快速开始

### 环境要求

- Python 3.10+
- Docker（可选，用于容器诊断功能）

### 安装步骤

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

### 验证安装

```bash
# 健康检查
curl http://localhost:8000/health

# 查看可用能力
curl http://localhost:8000/api/capabilities
```

## API 使用示例

### 主机资源监控

```bash
curl -X POST http://localhost:8000/api/capabilities/inspect_host/dispatch \
  -H "Content-Type: application/json" \
  -d '{"metrics": ["cpu", "memory", "disk"]}'
```

### 创建告警规则

```bash
curl -X POST http://localhost:8000/api/capabilities/manage_alerts/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "action": "create_rule",
    "name": "CPU 过高告警",
    "metric": "cpu_usage",
    "threshold": 80,
    "operator": ">",
    "severity": "warning"
  }'
```

### 查询活动告警

```bash
curl -X POST http://localhost:8000/api/capabilities/manage_alerts/dispatch \
  -H "Content-Type: application/json" \
  -d '{"action": "query_alerts", "status": "active"}'
```

## 项目结构

```
opsMind/
├── main.py                     # FastAPI 入口
├── settings.py                 # 配置管理
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── .gitignore                  # Git 忽略文件
│
├── engine/
│   ├── contracts.py            # 数据模型定义
│   ├── capabilities/
│   │   ├── base.py             # 能力基类
│   │   ├── host_monitor.py     # 主机监控
│   │   ├── alert_manager.py    # 告警管理
│   │   └── decorators.py       # 装饰器
│   ├── storage/
│   │   └── alert_store.py      # 告警存储
│   └── integrations/
│       └── data_sources/       # 数据源适配（后续）
│
├── api/                        # API 路由（后续）
│
└── frontend/                   # React 前端（后续）
```

## 核心能力

| 能力名称 | 描述 | 需要确认 |
|---------|------|---------|
| `inspect_host` | 主机资源监控 | 否 |
| `manage_alerts` | 告警规则管理 | 否 |
| `get_remediation_plan` | 获取修复预案 | 否 |
| `execute_remediation` | 执行修复 | 是 |

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|-------|------|-------|
| `LLM_API_KEY` | LLM API 密钥（必填） | - |
| `LLM_BASE_URL` | LLM API 地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名称 | `gpt-4o-mini` |
| `PORT` | 服务端口 | `8000` |
| `DEBUG` | 调试模式 | `false` |
| `DOCKER_HOST` | Docker 守护进程地址 | `unix:///var/run/docker.sock` |


## License

Apache 2.0
