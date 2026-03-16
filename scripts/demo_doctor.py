"""opsMind 演示环境体检脚本。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 允许从 scripts 目录直接执行：python scripts/demo_doctor.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_demo_data import ensure_access_log, seed_sqlite  # noqa: E402
from scripts.verify_demo_data import collect_demo_verification  # noqa: E402
from settings import RuntimeConfig  # noqa: E402


def build_demo_walkthrough(frontend_base_url: str) -> list[dict[str, str]]:
    """输出一条适合对外演示的页面讲解路线。"""
    return [
        {
            "step": "01",
            "title": "总览大盘",
            "url": f"{frontend_base_url}/",
            "focus": "先讲整体状态、热点服务和近期异常，让观众快速建立全局认知。",
        },
        {
            "step": "02",
            "title": "流量分析",
            "url": f"{frontend_base_url}/traffic?time_range=1h",
            "focus": "重点展示请求趋势、Top Path、错误样本和时间窗筛选联动。",
        },
        {
            "step": "03",
            "title": "资源分析",
            "url": f"{frontend_base_url}/resources?time_range=1h",
            "focus": "讲 CPU、内存、重启风险与热点分层，承接流量异常的资源视角。",
        },
        {
            "step": "04",
            "title": "异常中心",
            "url": f"{frontend_base_url}/incidents",
            "focus": "展示 incident 列表、证据链、摘要和从异常发起建议的入口。",
        },
        {
            "step": "05",
            "title": "建议中心",
            "url": f"{frontend_base_url}/recommendations?incidentId=incident_seed_001",
            "focus": "重点讲基线 / 建议 / diff 三视图、风险提示、审批与反馈。",
        },
        {
            "step": "06",
            "title": "AI 助手",
            "url": f"{frontend_base_url}/assistant?source=incident&incidentId=incident_seed_001&service_key=seed%2Fdemo-service&time_range=1h",
            "focus": "演示 AI 对当前上下文的诊断问答，以及只读命令建议。",
        },
        {
            "step": "07",
            "title": "任务中心",
            "url": f"{frontend_base_url}/tasks?taskId=task_seed_001",
            "focus": "展示任务状态、trace、artifact 和失败诊断视角。",
        },
        {
            "step": "08",
            "title": "质量看板与执行插件",
            "url": f"{frontend_base_url}/quality",
            "focus": "补充展示建议采纳率、AI 调用质量，再切到执行插件说明只读诊断边界。",
        },
    ]


def collect_demo_doctor_report(
    config: RuntimeConfig,
    *,
    frontend_base_url: str = "http://localhost:3000",
    backend_base_url: str = "http://localhost:8000",
) -> dict[str, Any]:
    """汇总演示环境体检结果，便于本地联调和对外展示。"""
    verification = collect_demo_verification(config)
    walkthrough = build_demo_walkthrough(frontend_base_url.rstrip("/"))
    readiness = "ready" if verification["ok"] else "blocked"
    # 默认建议一条从总览到建议、再回到任务与质量看板的讲解路径。
    next_actions = [
        "先打开总览页确认页面数据已渲染。",
        "从异常中心进入建议中心，再跳转到 AI 助手演示上下文联动。",
        "最后回到任务中心和质量看板收尾，强调可追踪与可评审。",
    ]
    if not verification["ok"]:
        next_actions = [
            "先执行 python scripts/seed_demo_data.py 补齐演示数据。",
            "再执行 python scripts/verify_demo_data.py 确认样本、任务与 artifact 完整。",
            "最后运行前端 smoke 或手动打开主控台页面复查。",
        ]

    return {
        "project": "opsMind",
        "readiness": readiness,
        "frontend_base_url": frontend_base_url.rstrip("/"),
        "backend_base_url": backend_base_url.rstrip("/"),
        "health_urls": {
            "frontend": frontend_base_url.rstrip("/"),
            "backend_health": f"{backend_base_url.rstrip('/')}/health",
            "dashboard_overview": f"{backend_base_url.rstrip('/')}/api/dashboard/overview",
        },
        "verification": verification,
        "walkthrough": walkthrough,
        "next_actions": next_actions,
    }


def write_demo_doctor_report(config: RuntimeConfig, report: dict[str, Any]) -> Path:
    """把体检结果写到 data/demo，方便后续留档或截图。"""
    config.ensure_directories()
    report_dir = (config.data_dir or (PROJECT_ROOT / "data")) / "demo"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "demo_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="opsMind 演示环境体检脚本")
    parser.add_argument("--seed", action="store_true", help="执行幂等 seed，补齐演示数据")
    parser.add_argument("--reset", action="store_true", help="执行 seed 时重置固定演示数据")
    parser.add_argument("--write-report", action="store_true", help="把体检结果写入 data/demo/demo_report.json")
    parser.add_argument("--frontend-base-url", default="http://localhost:3000", help="前端访问地址")
    parser.add_argument("--backend-base-url", default="http://localhost:8000", help="后端访问地址")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = RuntimeConfig.load_from_env()
    config.ensure_directories()

    if args.seed:
        # 这里保持幂等：同一个演示环境可以反复补齐数据，不要求每次都重置。
        seed_log_path = (config.raw_log_dir or (config.data_dir / "raw_logs")) / "access.seed.log"
        ensure_access_log(seed_log_path, reset=args.reset)
        seed_sqlite(config, reset=args.reset)

    report = collect_demo_doctor_report(
        config,
        frontend_base_url=args.frontend_base_url,
        backend_base_url=args.backend_base_url,
    )

    if args.write_report:
        report_path = write_demo_doctor_report(config, report)
        report["report_path"] = str(report_path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["readiness"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
