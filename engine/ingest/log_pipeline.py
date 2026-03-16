"""
访问日志流水线。

负责读取日志文件、解析、富化并输出聚合结果。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from engine.runtime.time_utils import ensure_utc_datetime, parse_utc_datetime, utc_now

from .aggregators import LogAggregators
from .log_enricher import LogEnricher
from .log_parser import AccessLogParser
from .log_samples import build_log_samples, collect_log_sample_candidates


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
        stats = self._build_load_stats(log_paths)
        return list(
            self._iter_filtered_records(
                log_paths,
                time_range=time_range,
                service_key=service_key,
                start_time=start_time,
                end_time=end_time,
                stats=stats,
            )
        )

    def summarize(self, log_paths: List[str], time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, object]:
        """读取日志并输出聚合摘要。"""
        stats = self._build_load_stats(log_paths)
        records = self._iter_filtered_records(
            log_paths,
            time_range=time_range,
            service_key=service_key,
            start_time=None,
            end_time=None,
            stats=stats,
        )
        summary = self.aggregators.summarize(records)
        summary.update(self._build_summary_meta(stats))
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
        stats = self._build_load_stats(log_paths)
        sample_candidates: List[Dict[str, object]] = []
        for item in self._iter_filtered_records(
            log_paths,
            time_range="24h",
            service_key=service_key,
            start_time=start_time,
            end_time=end_time,
            stats=stats,
        ):
            collect_log_sample_candidates(sample_candidates, item, limit=max(limit * 8, 32))
        return build_log_samples(sample_candidates, limit=limit)

    def _iter_filtered_records(
        self,
        log_paths: Iterable[str],
        time_range: str,
        service_key: Optional[str],
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        stats: Dict[str, int],
    ):
        cutoff = self._resolve_cutoff(time_range)
        normalized_start = self._normalize_time(start_time) if start_time else cutoff
        normalized_end = self._normalize_time(end_time) if end_time else None

        for log_path in log_paths:
            path = Path(log_path)
            if not path.exists() or not path.is_file():
                stats["missing_files"] += 1
                continue

            stats["scanned_files"] += 1
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for raw_line in handle:
                        stats["lines_read"] += 1
                        line = raw_line.strip()
                        if not line:
                            continue

                        parsed = self.parser.parse_line(line)
                        if not parsed:
                            stats["parse_failures"] += 1
                            continue
                        stats["parsed_lines"] += 1

                        try:
                            enriched = self.enricher.enrich(parsed, host_hint=path.stem)
                        except Exception:  # noqa: BLE001
                            stats["enrich_failures"] += 1
                            enriched = self.enricher.fallback_enrich(parsed, host_hint=path.stem)

                        item_time = self._parse_record_time(str(enriched.get("timestamp") or ""))
                        if item_time is None:
                            stats["parse_failures"] += 1
                            continue
                        if item_time < normalized_start:
                            stats["time_filtered"] += 1
                            continue
                        if normalized_end and item_time > normalized_end:
                            stats["time_filtered"] += 1
                            continue
                        if service_key and enriched.get("service_key") != service_key:
                            stats["service_filtered"] += 1
                            continue

                        stats["matched_records"] += 1
                        yield enriched
            except OSError:
                stats["unreadable_files"] += 1

    def _build_load_stats(self, log_paths: Iterable[str]) -> Dict[str, int]:
        return {
            "configured_paths": len(list(log_paths)) if not isinstance(log_paths, list) else len(log_paths),
            "scanned_files": 0,
            "missing_files": 0,
            "unreadable_files": 0,
            "lines_read": 0,
            "parsed_lines": 0,
            "matched_records": 0,
            "parse_failures": 0,
            "enrich_failures": 0,
            "time_filtered": 0,
            "service_filtered": 0,
        }

    def _build_summary_meta(self, stats: Dict[str, int]) -> Dict[str, object]:
        reasons: List[str] = []
        status = "ready"
        message = "访问日志已正常加载"

        if stats["configured_paths"] == 0:
            status = "unavailable"
            reasons.append("no_log_source")
            message = "当前未配置访问日志源"
        else:
            if stats["missing_files"] > 0:
                reasons.append("missing_log_files")
            if stats["unreadable_files"] > 0:
                reasons.append("unreadable_log_files")
            if stats["parse_failures"] > 0:
                reasons.append("parse_failures")
            if stats["enrich_failures"] > 0:
                reasons.append("enrich_failures")

            if stats["matched_records"] == 0:
                if reasons:
                    status = "degraded"
                    message = "访问日志存在缺失或解析失败，已降级返回空摘要"
                else:
                    status = "empty"
                    reasons.append("no_records_in_window")
                    message = "当前时间窗内没有命中访问日志"
            elif reasons:
                status = "degraded"
                message = "部分访问日志解析失败，结果已按可用数据生成"

        return {
            "data_status": status,
            "data_message": message,
            "degradation_reasons": reasons,
            "load_stats": stats,
        }

    def _parse_record_time(self, iso_text: str) -> Optional[datetime]:
        try:
            parsed = parse_utc_datetime(iso_text)
        except ValueError:
            return None
        return self._normalize_time(parsed)

    def _resolve_cutoff(self, time_range: str) -> datetime:
        time_range = (time_range or "1h").strip().lower()
        now_utc = self._normalize_time(utc_now())
        if time_range.endswith("m"):
            minutes = int(time_range[:-1] or "60")
            return now_utc - timedelta(minutes=minutes)
        if time_range.endswith("h"):
            hours = int(time_range[:-1] or "1")
            return now_utc - timedelta(hours=hours)
        if time_range.endswith("d"):
            days = int(time_range[:-1] or "1")
            return now_utc - timedelta(days=days)
        return now_utc - timedelta(hours=1)

    def _normalize_time(self, value: datetime) -> datetime:
        return ensure_utc_datetime(value).replace(tzinfo=None)
