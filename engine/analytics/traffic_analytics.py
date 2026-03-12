"""
流量分析引擎。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from engine.ingest.log_pipeline import LogPipeline


class TrafficAnalyticsEngine:
    """统一对外提供流量统计摘要。"""

    def __init__(self, raw_log_dir: Path):
        self.pipeline = LogPipeline(raw_log_dir)

    def summarize(self, log_paths: List[str], time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, object]:
        return self.pipeline.summarize(log_paths, time_range=time_range, service_key=service_key)

    def sample_records(
        self,
        log_paths: List[str],
        service_key: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 8,
    ) -> List[Dict[str, object]]:
        """为异常详情提供可直接阅读的访问样本。"""
        return self.pipeline.sample_records(
            log_paths,
            service_key=service_key,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
