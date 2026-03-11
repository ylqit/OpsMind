"""
流量分析引擎。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from engine.ingest.log_pipeline import LogPipeline


class TrafficAnalyticsEngine:
    """统一对外提供流量统计摘要。"""

    def __init__(self, raw_log_dir: Path):
        self.pipeline = LogPipeline(raw_log_dir)

    def summarize(self, log_paths: List[str], time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, object]:
        return self.pipeline.summarize(log_paths, time_range=time_range, service_key=service_key)
