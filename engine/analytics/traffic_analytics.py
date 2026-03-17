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

    REQUEST_BASELINE_DEVIATION_THRESHOLD = 30.0
    ERROR_RATE_DEVIATION_THRESHOLD = 2.0
    ERROR_RATE_RATIO_THRESHOLD = 1.5

    def __init__(self, raw_log_dir: Path):
        self.pipeline = LogPipeline(raw_log_dir)

    def summarize(self, log_paths: List[str], time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, object]:
        summary = self.pipeline.summarize(log_paths, time_range=time_range, service_key=service_key)
        summary["baseline_summary"] = self._build_baseline_summary(summary)
        return summary

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

    def _build_baseline_summary(self, summary: Dict[str, object]) -> Dict[str, object]:
        trend = summary.get("trend")
        points = [item for item in trend if isinstance(item, dict)] if isinstance(trend, list) else []
        if len(points) < 2:
            return {
                "status": "unavailable",
                "source": "historical_trend",
                "headline": "当前时间窗点位不足，暂时无法形成流量基线。",
                "message": "至少需要两段以上的趋势点位，才能比较当前窗口与历史基线的偏移。",
                "highlights": [],
                "reference_points": 0,
            }

        current_point = points[-1]
        baseline_points = [item for item in points[:-1] if self._extract_metric_value(item.get("requests")) > 0 or self._extract_metric_value(item.get("errors")) > 0]
        if not baseline_points:
            return {
                "status": "unavailable",
                "source": "historical_trend",
                "headline": "当前趋势点位过少，暂时无法形成稳定流量基线。",
                "message": "历史窗口没有足够的有效请求点位，流量偏移只能结合当前窗口做人工判断。",
                "highlights": [],
                "reference_points": 0,
            }

        baseline_request_volume = sum(self._extract_metric_value(item.get("requests")) for item in baseline_points) / len(baseline_points)
        baseline_request_total = sum(self._extract_metric_value(item.get("requests")) for item in baseline_points)
        baseline_error_total = sum(self._extract_metric_value(item.get("errors")) for item in baseline_points)
        baseline_error_rate = (baseline_error_total / baseline_request_total * 100.0) if baseline_request_total > 0 else 0.0

        current_request_volume = self._extract_metric_value(current_point.get("requests"))
        current_error_rate = self._safe_error_rate(
            errors=self._extract_metric_value(current_point.get("errors")),
            requests=current_request_volume,
            fallback=self._extract_metric_value(summary.get("error_rate")),
        )

        highlights: List[Dict[str, object]] = []
        request_delta_percent = self._calculate_delta_percent(current_request_volume, baseline_request_volume)
        if request_delta_percent is not None and abs(request_delta_percent) >= self.REQUEST_BASELINE_DEVIATION_THRESHOLD:
            direction = "up" if request_delta_percent >= 0 else "down"
            highlights.append(
                {
                    "highlight_id": "traffic_request_volume",
                    "layer": "traffic",
                    "metric": "request_volume",
                    "title": (
                        f"最新请求量高于基线 {abs(request_delta_percent):.1f}%"
                        if direction == "up"
                        else f"最新请求量低于基线 {abs(request_delta_percent):.1f}%"
                    ),
                    "summary": (
                        f"最新趋势点位请求量约 {current_request_volume:.0f}，"
                        f"相较历史基线 {baseline_request_volume:.0f} 偏移 {request_delta_percent:.1f}%。"
                    ),
                    "current_value": round(current_request_volume, 2),
                    "baseline_value": round(baseline_request_volume, 2),
                    "delta_value": round(current_request_volume - baseline_request_volume, 2),
                    "delta_percent": round(request_delta_percent, 2),
                    "unit": "req",
                    "severity": "high" if abs(request_delta_percent) >= 60 else "medium",
                    "direction": direction,
                    "source": "historical_trend",
                    "next_step": "优先核对热点路径、来源 IP 和入口限流策略，确认是否存在流量突增或异常放量。",
                    "timestamp": str(current_point.get("timestamp") or ""),
                }
            )

        error_rate_delta = current_error_rate - baseline_error_rate
        error_rate_ratio = self._calculate_ratio(current_error_rate, baseline_error_rate)
        if (
            abs(error_rate_delta) >= self.ERROR_RATE_DEVIATION_THRESHOLD
            or (error_rate_ratio is not None and error_rate_ratio >= self.ERROR_RATE_RATIO_THRESHOLD)
        ):
            direction = "up" if error_rate_delta >= 0 else "down"
            highlights.append(
                {
                    "highlight_id": "traffic_error_rate",
                    "layer": "traffic",
                    "metric": "error_rate",
                    "title": (
                        f"最新错误率高于基线 {abs(error_rate_delta):.1f} 个百分点"
                        if direction == "up"
                        else f"最新错误率低于基线 {abs(error_rate_delta):.1f} 个百分点"
                    ),
                    "summary": (
                        f"最新趋势点位错误率约 {current_error_rate:.2f}%，"
                        f"历史基线约 {baseline_error_rate:.2f}%。"
                    ),
                    "current_value": round(current_error_rate, 2),
                    "baseline_value": round(baseline_error_rate, 2),
                    "delta_value": round(error_rate_delta, 2),
                    "delta_percent": round(error_rate_ratio * 100 - 100, 2) if error_rate_ratio is not None else None,
                    "unit": "%",
                    "severity": "high" if error_rate_delta >= 5 else "medium",
                    "direction": direction,
                    "source": "historical_trend",
                    "next_step": "优先对照错误样本和上游依赖状态，判断是入口配置失衡还是下游异常放大了错误率。",
                    "timestamp": str(current_point.get("timestamp") or ""),
                }
            )

        highlights.sort(
            key=lambda item: (
                -self._severity_rank(str(item.get("severity") or "medium")),
                -abs(self._extract_metric_value(item.get("delta_percent") or item.get("delta_value"))),
                str(item.get("metric") or ""),
            )
        )
        if highlights:
            return {
                "status": "ready",
                "source": "historical_trend",
                "headline": str(highlights[0]["title"]),
                "message": "已基于趋势窗口构建流量基线，可用于判断最新请求量和错误率是否偏离常态。",
                "highlights": highlights[:3],
                "reference_points": len(baseline_points),
                "current_timestamp": str(current_point.get("timestamp") or ""),
            }

        return {
            "status": "ready",
            "source": "historical_trend",
            "headline": "当前流量未明显偏离近期基线。",
            "message": "最新趋势点位与历史窗口接近，当前流量侧没有观察到明显的异常偏移。",
            "highlights": [],
            "reference_points": len(baseline_points),
            "current_timestamp": str(current_point.get("timestamp") or ""),
        }

    def _extract_metric_value(self, value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _safe_error_rate(self, *, errors: float, requests: float, fallback: float) -> float:
        if requests > 0:
            return errors / requests * 100.0
        return fallback

    def _calculate_delta_percent(self, current_value: float, baseline_value: float) -> Optional[float]:
        if baseline_value <= 0:
            return None
        return (current_value - baseline_value) / baseline_value * 100.0

    def _calculate_ratio(self, current_value: float, baseline_value: float) -> Optional[float]:
        if baseline_value <= 0:
            return None if current_value <= 0 else float("inf")
        return current_value / baseline_value

    def _severity_rank(self, severity: str) -> int:
        if severity == "high":
            return 2
        if severity == "medium":
            return 1
        return 0
