"""
访问日志流水线。

负责读取日志文件、解析、富化并输出聚合结果。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .aggregators import LogAggregators
from .log_enricher import LogEnricher
from .log_parser import AccessLogParser


class LogPipeline:
    """访问日志流水线。"""

    def __init__(self, raw_log_dir: Path):
        self.raw_log_dir = raw_log_dir
        self.raw_log_dir.mkdir(parents=True, exist_ok=True)
        self.parser = AccessLogParser()
        self.enricher = LogEnricher()
        self.aggregators = LogAggregators()

    def load_records(
        self,
        log_paths: List[str],
        time_range: str = "1h",
        service_key: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, object]]:
        """加载并过滤日志记录。"""
        cutoff = self._resolve_cutoff(time_range)
        normalized_start = self._normalize_time(start_time) if start_time else cutoff
        normalized_end = self._normalize_time(end_time) if end_time else None
        records: List[Dict[str, object]] = []
        for log_path in log_paths:
            path = Path(log_path)
            if not path.exists() or not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                parsed = self.parser.parse_line(line)
                if not parsed:
                    continue
                enriched = self.enricher.enrich(parsed, host_hint=path.stem)
                item_time = self._normalize_time(datetime.fromisoformat(str(enriched["timestamp"]).replace("Z", "+00:00")))
                if item_time < normalized_start:
                    continue
                if normalized_end and item_time > normalized_end:
                    continue
                if service_key and enriched.get("service_key") != service_key:
                    continue
                records.append(enriched)
        return records

    def summarize(self, log_paths: List[str], time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, object]:
        """读取日志并输出聚合摘要。"""
        records = self.load_records(log_paths, time_range=time_range, service_key=service_key)
        summary = self.aggregators.summarize(records)
        summary["records_sample"] = records[:20]
        return summary

    def sample_records(
        self,
        log_paths: List[str],
        service_key: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 8,
    ) -> List[Dict[str, object]]:
        """按时间窗获取更适合排障阅读的日志样本。"""
        records = self.load_records(
            log_paths,
            time_range="24h",
            service_key=service_key,
            start_time=start_time,
            end_time=end_time,
        )
        interesting = [
            item for item in records
            if int(item.get("status") or 0) >= 500 or float(item.get("request_time") or 0.0) >= 1
        ]
        source = interesting or records
        return source[:limit]

    def _resolve_cutoff(self, time_range: str) -> datetime:
        time_range = (time_range or "1h").strip().lower()
        if time_range.endswith("m"):
            minutes = int(time_range[:-1] or "60")
            return datetime.utcnow() - timedelta(minutes=minutes)
        if time_range.endswith("h"):
            hours = int(time_range[:-1] or "1")
            return datetime.utcnow() - timedelta(hours=hours)
        if time_range.endswith("d"):
            days = int(time_range[:-1] or "1")
            return datetime.utcnow() - timedelta(days=days)
        return datetime.utcnow() - timedelta(hours=1)

    def _normalize_time(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
