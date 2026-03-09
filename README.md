# opsMind

**智能运维助手** - 可控、可追溯的运维诊断与告警管理

## 项目定位

opsMind 是一个独立设计的 AIOps 开源项目，提供：

- **主机资源监控** - CPU、内存、磁盘、网络实时监控
- **告警管理** - 告警规则创建、查询、确认、解决
- **修复预案** - 故障自动修复方案推荐
- **容器诊断** - Docker 容器状态检查
- **K8s YAML 生成** - Kubernetes 配置文件生成
- **日志分析** - 日志文件错误模式识别

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
│   │   ├── decorators.py       # 装饰器
│   │   ├── host_monitor.py     # 主机监控
│   │   ├── container_inspector.py  # 容器诊断
│   │   ├── log_analyzer.py     # 日志分析
│   │   ├── k8s_yaml_generator.py  # K8s YAML 生成
│   │   ├── alert_manager.py    # 告警管理
│   │   ├── remediation.py      # 修复预案
│   │   └── execute_remediation.py  # 执行修复
│   ├── storage/
│   │   └── alert_store.py      # 告警存储
│   └── integrations/
│       └── data_sources/       # 数据源适配
│
├── api/
│   └── routes.py               # REST API 路由
│
└── frontend/                   # React + TypeScript 前端
    ├── src/
    │   ├── App.tsx             # 主应用
    │   ├── api/client.ts       # API 客户端
    │   ├── stores/             # Zustand 状态管理
    │   └── components/         # React 组件
    │       ├── Dashboard/      # 监控仪表盘
    │       ├── AlertPanel/     # 告警管理
    │       └── ContainerList/  # 容器管理
    └── package.json
```

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


## License

Apache 2.0
