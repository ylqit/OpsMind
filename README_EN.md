# opsMind

OpsMind is an operations analytics platform built with FastAPI and React for unified traffic, resource, incident, recommendation, and task tracking workflows.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19+-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)

[简体中文](README.md) | English

## Features

- Unified overview dashboard for key status, hot services, and recent incidents
- Traffic analytics for request trends, status codes, paths, source IPs, user agents, and error samples
- Resource analytics across host, container, pod, and service dimensions
- Incident center with evidence chains, summaries, and analysis entry points
- Recommendation center with baseline / recommended / diff views, YAML preview, copy, export, and feedback
- Task center with task status, stages, traces, artifacts, and failure diagnosis
- AI assistant and metrics panel for provider status, diagnosis Q&A, and quality metrics
- Read-only executor plugins for Linux, Docker, and Kubernetes diagnostics

## Architecture

```text
logs / metrics / assets
  -> traffic / resource analytics
  -> incidents
  -> recommendations
  -> tasks / traces / artifacts
  -> ai assistant / quality metrics
```

For a detailed module walkthrough, see [docs/architecture.md](docs/architecture.md).

## Tech Stack

### Backend

- Python 3.10+
- FastAPI
- SQLite
- Custom task runtime

### Frontend

- React 19
- TypeScript
- Vite
- Ant Design 5
- Zustand

## Project Structure

```text
opsMind/
├─ api/                  # Routes, dependency wiring, WebSocket APIs
├─ engine/
│  ├─ analytics/         # Traffic, resource, and correlation analytics
│  ├─ domain/            # Asset, signal, incident, and recommendation services
│  ├─ ingest/            # Log parsing and aggregation
│  ├─ llm/               # AI providers and router
│  ├─ operations/        # Executor plugins and ops actions
│  ├─ runtime/           # Tasks, state machine, traces, artifacts
│  └─ storage/           # SQLite and repositories
├─ frontend/             # React frontend
├─ scripts/              # Demo data and helper scripts
├─ data/                 # Local runtime data
└─ docs/                 # Project docs
```

## Documentation

- [Architecture](docs/architecture.md)
- [Demo Scenarios](docs/demo-scenarios.md)
- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security](SECURITY.md)

## Quick Start

### Requirements

- Python 3.10+
- Node.js 18+
- Docker (optional)
- Prometheus (optional)

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

### Local Development

Backend:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Configuration

See `.env.example` for the environment variable template.

Common settings:

- `BACKEND_PORT`: backend port, default `8000`
- `FRONTEND_PORT`: frontend port, default `3000`
- `DATA_SOURCES`: enabled data sources, default `logfile`
- `ACCESS_LOG_PATHS`: access log paths
- `ENABLE_SEED`: whether to initialize demo data
- `SEED_RESET`: whether to reset fixed demo samples
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`: AI provider settings
- `PROMETHEUS_URL`: Prometheus endpoint
- `DOCKER_HOST`: Docker socket or pipe address

## Demo Data

The repository includes demo data scripts:

```bash
python scripts/seed_demo_data.py
python scripts/verify_demo_data.py
python scripts/demo_doctor.py --seed --write-report
```

- `seed_demo_data.py`: initializes logs, incidents, recommendations, tasks, and artifacts
- `verify_demo_data.py`: checks demo data integrity, scenario coverage, and three-view artifacts
- `demo_doctor.py`: generates a demo environment report, recommended walkthrough order, and missing items, then writes `data/demo/demo_report.json`

Recommended demo flows are documented in [docs/demo-scenarios.md](docs/demo-scenarios.md).

## API

Primary product routes:

- `/api/dashboard/*`
- `/api/traffic/*`
- `/api/resources/*`
- `/api/incidents/*`
- `/api/recommendations/*`
- `/api/tasks/*`
- `/api/metrics/*`
- `/api/executors/*`
- `/api/ai/*`

Debug-only routes:

- `api/legacy_routes.py`

## Development

Frontend build:

```bash
cd frontend
npm run build
```

## Contributing

Contributions through Issues and Pull Requests are welcome.

- Review the README, architecture doc, and demo scenarios before opening a new issue
- When submitting a PR, explain the background, key changes, and local verification steps
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the detailed collaboration guide
- See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community participation standards

## License

Apache 2.0
