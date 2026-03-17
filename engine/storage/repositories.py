"""
SQLite repositories。

统一封装各类核心实体的读写，避免业务层拼接 SQL。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from engine.runtime.models import (
    AICallLog,
    AIProviderConfigRecord,
    AIWritebackRecord,
    AnalysisSession,
    ArtifactRef,
    Asset,
    ExecutorAuditRecord,
    ExecutorPluginRecord,
    ExecutorRunStatus,
    Incident,
    Recommendation,
    RecommendationFeedback,
    Signal,
    TaskApproval,
    TaskError,
    TaskRecord,
    UsageMetricsDailyRecord,
)
from engine.runtime.time_utils import parse_optional_utc_datetime, parse_utc_datetime, utc_now, utc_now_iso

from .sqlite import SQLiteDatabase


# 统一使用 ensure_ascii=False，避免中文摘要和说明字段被转义后影响前端展示。
def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


# 仓储层统一负责把数据库中的时间解析成 UTC 语义，业务层不再自己兜底。
def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    return parse_optional_utc_datetime(value)


class TaskRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, task: TaskRecord) -> TaskRecord:
        self.db.execute(
            """
            INSERT OR REPLACE INTO tasks (
                task_id, task_type, status, current_stage, progress, progress_message,
                trace_id, payload_json, result_ref_json, error_json, approval_json, created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.task_type.value,
                task.status.value,
                task.current_stage.value,
                task.progress,
                task.progress_message,
                task.trace_id,
                _to_json(task.payload),
                _to_json(task.result_ref) if task.result_ref else None,
                task.error.model_dump_json() if task.error else None,
                task.approval.model_dump_json() if task.approval else None,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
                task.completed_at.isoformat() if task.completed_at else None,
            ),
        )
        return task

    def get(self, task_id: str) -> Optional[TaskRecord]:
        row = self.db.fetchone("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        if not row:
            return None
        error_json = _from_json(row["error_json"], None)
        approval_json = _from_json(row["approval_json"], None)
        return TaskRecord(
            task_id=row["task_id"],
            task_type=row["task_type"],
            status=row["status"],
            current_stage=row["current_stage"],
            progress=row["progress"],
            progress_message=row["progress_message"] or "",
            trace_id=row["trace_id"],
            payload=_from_json(row["payload_json"], {}),
            result_ref=_from_json(row["result_ref_json"], None),
            error=TaskError(**error_json) if error_json else None,
            approval=TaskApproval(**approval_json) if approval_json else None,
            created_at=parse_utc_datetime(row["created_at"]),
            updated_at=parse_utc_datetime(row["updated_at"]),
            completed_at=_parse_dt(row["completed_at"]),
        )

    def list(self, task_type: Optional[str] = None, status: Optional[str] = None) -> List[TaskRecord]:
        clauses = []
        params: List[Any] = []
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.fetchall(f"SELECT task_id FROM tasks {where_clause} ORDER BY updated_at DESC", params)
        items: List[TaskRecord] = []
        for row in rows:
            task = self.get(row["task_id"])
            if task:
                items.append(task)
        return items

    def list_by_created_range(self, start_at: datetime, end_at: datetime) -> List[TaskRecord]:
        rows = self.db.fetchall(
            """
            SELECT task_id FROM tasks
            WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at ASC
            """,
            (start_at.isoformat(), end_at.isoformat()),
        )
        items: List[TaskRecord] = []
        for row in rows:
            task = self.get(row["task_id"])
            if task:
                items.append(task)
        return items


class ArtifactRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, artifact: ArtifactRef) -> ArtifactRef:
        self.db.execute(
            """
            INSERT OR REPLACE INTO artifacts (
                artifact_id, task_id, kind, path, preview, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.task_id,
                artifact.kind,
                artifact.path,
                artifact.preview,
                artifact.size_bytes,
                artifact.created_at.isoformat(),
            ),
        )
        return artifact

    def get(self, task_id: str, artifact_id: str) -> Optional[ArtifactRef]:
        row = self.db.fetchone(
            "SELECT * FROM artifacts WHERE task_id = ? AND artifact_id = ?",
            (task_id, artifact_id),
        )
        if not row:
            return None
        return ArtifactRef(
            artifact_id=row["artifact_id"],
            task_id=row["task_id"],
            kind=row["kind"],
            path=row["path"],
            preview=row["preview"] or "",
            size_bytes=row["size_bytes"],
            created_at=parse_utc_datetime(row["created_at"]),
        )

    def list_by_task(self, task_id: str) -> List[ArtifactRef]:
        rows = self.db.fetchall("SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        return [
            ArtifactRef(
                artifact_id=row["artifact_id"],
                task_id=row["task_id"],
                kind=row["kind"],
                path=row["path"],
                preview=row["preview"] or "",
                size_bytes=row["size_bytes"],
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]


class AssetRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, asset: Asset) -> Asset:
        self.db.execute(
            """
            INSERT OR REPLACE INTO assets (
                asset_id, asset_type, name, namespace, service_key, labels_json, source_refs_json,
                health_status, unmapped, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset.asset_id,
                asset.asset_type.value,
                asset.name,
                asset.namespace,
                asset.service_key,
                _to_json(asset.labels),
                _to_json(asset.source_refs),
                asset.health_status,
                1 if asset.unmapped else 0,
                asset.created_at.isoformat(),
                asset.updated_at.isoformat(),
            ),
        )
        return asset

    def list(self, asset_type: Optional[str] = None, service_key: Optional[str] = None, health_status: Optional[str] = None) -> List[Asset]:
        clauses = []
        params: List[Any] = []
        if asset_type:
            clauses.append("asset_type = ?")
            params.append(asset_type)
        if service_key:
            clauses.append("service_key = ?")
            params.append(service_key)
        if health_status:
            clauses.append("health_status = ?")
            params.append(health_status)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.fetchall(f"SELECT * FROM assets {where_clause} ORDER BY name ASC", params)
        return [
            Asset(
                asset_id=row["asset_id"],
                asset_type=row["asset_type"],
                name=row["name"],
                namespace=row["namespace"],
                service_key=row["service_key"],
                labels=_from_json(row["labels_json"], {}),
                source_refs=_from_json(row["source_refs_json"], {}),
                health_status=row["health_status"],
                unmapped=bool(row["unmapped"]),
                created_at=parse_utc_datetime(row["created_at"]),
                updated_at=parse_utc_datetime(row["updated_at"]),
            )
            for row in rows
        ]


class SignalRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, signal: Signal) -> Signal:
        self.db.execute(
            """
            INSERT OR REPLACE INTO signals (
                signal_id, signal_type, timestamp, asset_id, service_key, severity, payload_json, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.signal_id,
                signal.signal_type.value,
                signal.timestamp.isoformat(),
                signal.asset_id,
                signal.service_key,
                signal.severity,
                _to_json(signal.payload),
                signal.source,
                signal.created_at.isoformat(),
            ),
        )
        return signal

    def list(
        self,
        signal_type: Optional[str] = None,
        service_key: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Signal]:
        clauses: List[str] = []
        params: List[Any] = []
        if signal_type:
            clauses.append("signal_type = ?")
            params.append(signal_type)
        if service_key:
            clauses.append("service_key = ?")
            params.append(service_key)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            clauses.append("timestamp <= ?")
            params.append(until.isoformat())

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(limit, 1000))
        rows = self.db.fetchall(
            f"""
            SELECT * FROM signals
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            [*params, safe_limit],
        )
        return [
            Signal(
                signal_id=row["signal_id"],
                signal_type=row["signal_type"],
                timestamp=parse_utc_datetime(row["timestamp"]),
                asset_id=row["asset_id"],
                service_key=row["service_key"],
                severity=row["severity"],
                payload=_from_json(row["payload_json"], {}),
                source=row["source"],
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]


class IncidentRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, incident: Incident) -> Incident:
        self.db.execute(
            """
            INSERT OR REPLACE INTO incidents (
                incident_id, title, severity, status, time_window_start, time_window_end, service_key,
                related_asset_ids_json, evidence_refs_json, summary, confidence, recommended_actions_json,
                reasoning_tags_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident.incident_id,
                incident.title,
                incident.severity,
                incident.status.value,
                incident.time_window_start.isoformat(),
                incident.time_window_end.isoformat(),
                incident.service_key,
                _to_json(incident.related_asset_ids),
                _to_json(incident.evidence_refs),
                incident.summary,
                incident.confidence,
                _to_json(incident.recommended_actions),
                _to_json(incident.reasoning_tags),
                incident.created_at.isoformat(),
                incident.updated_at.isoformat(),
            ),
        )
        return incident

    def get(self, incident_id: str) -> Optional[Incident]:
        row = self.db.fetchone("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
        if not row:
            return None
        return Incident(
            incident_id=row["incident_id"],
            title=row["title"],
            severity=row["severity"],
            status=row["status"],
            time_window_start=parse_utc_datetime(row["time_window_start"]),
            time_window_end=parse_utc_datetime(row["time_window_end"]),
            service_key=row["service_key"],
            related_asset_ids=_from_json(row["related_asset_ids_json"], []),
            evidence_refs=_from_json(row["evidence_refs_json"], []),
            summary=row["summary"],
            confidence=row["confidence"],
            recommended_actions=_from_json(row["recommended_actions_json"], []),
            reasoning_tags=_from_json(row["reasoning_tags_json"], []),
            created_at=parse_utc_datetime(row["created_at"]),
            updated_at=parse_utc_datetime(row["updated_at"]),
        )

    def list(self, status: Optional[str] = None, severity: Optional[str] = None, service_key: Optional[str] = None) -> List[Incident]:
        clauses = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if service_key:
            clauses.append("service_key = ?")
            params.append(service_key)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.fetchall(f"SELECT incident_id FROM incidents {where_clause} ORDER BY created_at DESC", params)
        items: List[Incident] = []
        for row in rows:
            incident = self.get(row["incident_id"])
            if incident:
                items.append(incident)
        return items

    def list_by_ids(self, incident_ids: List[str]) -> List[Incident]:
        unique_ids = [item for item in dict.fromkeys(incident_ids) if item]
        if not unique_ids:
            return []
        placeholders = ",".join(["?"] * len(unique_ids))
        rows = self.db.fetchall(
            f"SELECT incident_id FROM incidents WHERE incident_id IN ({placeholders})",
            unique_ids,
        )
        items: List[Incident] = []
        for row in rows:
            incident = self.get(row["incident_id"])
            if incident:
                items.append(incident)
        return items


class RecommendationRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, recommendation: Recommendation) -> Recommendation:
        self.db.execute(
            """
            INSERT OR REPLACE INTO recommendations (
                recommendation_id, incident_id, target_asset_id, kind, confidence, observation,
                recommendation, risk_note, artifact_refs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation.recommendation_id,
                recommendation.incident_id,
                recommendation.target_asset_id,
                recommendation.kind.value,
                recommendation.confidence,
                recommendation.observation,
                recommendation.recommendation,
                recommendation.risk_note,
                _to_json(recommendation.artifact_refs),
                recommendation.created_at.isoformat(),
                recommendation.updated_at.isoformat(),
            ),
        )
        return recommendation

    def get(self, recommendation_id: str) -> Optional[Recommendation]:
        row = self.db.fetchone("SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,))
        if not row:
            return None
        return Recommendation(
            recommendation_id=row["recommendation_id"],
            incident_id=row["incident_id"],
            target_asset_id=row["target_asset_id"],
            kind=row["kind"],
            confidence=row["confidence"],
            observation=row["observation"],
            recommendation=row["recommendation"],
            risk_note=row["risk_note"],
            artifact_refs=_from_json(row["artifact_refs_json"], []),
            created_at=parse_utc_datetime(row["created_at"]),
            updated_at=parse_utc_datetime(row["updated_at"]),
        )

    def list_by_incident(self, incident_id: str) -> List[Recommendation]:
        rows = self.db.fetchall("SELECT recommendation_id FROM recommendations WHERE incident_id = ? ORDER BY created_at DESC", (incident_id,))
        items: List[Recommendation] = []
        for row in rows:
            recommendation = self.get(row["recommendation_id"])
            if recommendation:
                items.append(recommendation)
        return items


class RecommendationFeedbackRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, feedback: RecommendationFeedback) -> RecommendationFeedback:
        self.db.execute(
            """
            INSERT OR REPLACE INTO recommendation_feedback (
                feedback_id, recommendation_id, incident_id, task_id, action,
                reason_code, comment, operator, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback.feedback_id,
                feedback.recommendation_id,
                feedback.incident_id,
                feedback.task_id,
                feedback.action.value,
                feedback.reason_code,
                feedback.comment,
                feedback.operator,
                feedback.created_at.isoformat(),
            ),
        )
        return feedback

    def list_by_recommendation(self, recommendation_id: str, limit: int = 50) -> List[RecommendationFeedback]:
        safe_limit = max(1, min(limit, 200))
        rows = self.db.fetchall(
            """
            SELECT * FROM recommendation_feedback
            WHERE recommendation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (recommendation_id, safe_limit),
        )
        return [
            RecommendationFeedback(
                feedback_id=row["feedback_id"],
                recommendation_id=row["recommendation_id"],
                incident_id=row["incident_id"],
                task_id=row["task_id"],
                action=row["action"],
                reason_code=row["reason_code"] or "",
                comment=row["comment"] or "",
                operator=row["operator"] or "anonymous",
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def list_by_incident(self, incident_id: str, limit: int = 100) -> List[RecommendationFeedback]:
        safe_limit = max(1, min(limit, 300))
        rows = self.db.fetchall(
            """
            SELECT * FROM recommendation_feedback
            WHERE incident_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (incident_id, safe_limit),
        )
        return [
            RecommendationFeedback(
                feedback_id=row["feedback_id"],
                recommendation_id=row["recommendation_id"],
                incident_id=row["incident_id"],
                task_id=row["task_id"],
                action=row["action"],
                reason_code=row["reason_code"] or "",
                comment=row["comment"] or "",
                operator=row["operator"] or "anonymous",
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def summarize_by_recommendation(self, recommendation_id: str) -> dict[str, int]:
        rows = self.db.fetchall(
            """
            SELECT action, COUNT(1) AS count
            FROM recommendation_feedback
            WHERE recommendation_id = ?
            GROUP BY action
            """,
            (recommendation_id,),
        )
        summary = {"adopt": 0, "reject": 0, "rewrite": 0}
        for row in rows:
            action = str(row["action"])
            if action in summary:
                summary[action] = int(row["count"])
        return summary

    def list_by_created_range(self, start_at: datetime, end_at: datetime) -> List[RecommendationFeedback]:
        rows = self.db.fetchall(
            """
            SELECT * FROM recommendation_feedback
            WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at ASC
            """,
            (start_at.isoformat(), end_at.isoformat()),
        )
        return [
            RecommendationFeedback(
                feedback_id=row["feedback_id"],
                recommendation_id=row["recommendation_id"],
                incident_id=row["incident_id"],
                task_id=row["task_id"],
                action=row["action"],
                reason_code=row["reason_code"] or "",
                comment=row["comment"] or "",
                operator=row["operator"] or "anonymous",
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]


class AICallLogRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, call_log: AICallLog) -> AICallLog:
        self.db.execute(
            """
            INSERT OR REPLACE INTO ai_call_logs (
                call_id, provider_name, model, source, endpoint, task_id,
                prompt_preview, response_preview, status, error_code, error_message,
                latency_ms, request_tokens, response_tokens, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_log.call_id,
                call_log.provider_name,
                call_log.model,
                call_log.source,
                call_log.endpoint,
                call_log.task_id,
                call_log.prompt_preview,
                call_log.response_preview,
                call_log.status.value,
                call_log.error_code,
                call_log.error_message,
                call_log.latency_ms,
                call_log.request_tokens,
                call_log.response_tokens,
                call_log.created_at.isoformat(),
            ),
        )
        return call_log

    def list(self, provider_name: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[AICallLog]:
        clauses = []
        params: List[Any] = []
        if provider_name:
            clauses.append("provider_name = ?")
            params.append(provider_name)
        if status:
            clauses.append("status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(limit, 500))
        rows = self.db.fetchall(
            f"SELECT * FROM ai_call_logs {where_clause} ORDER BY created_at DESC LIMIT ?",
            [*params, safe_limit],
        )
        return [
            AICallLog(
                call_id=row["call_id"],
                provider_name=row["provider_name"],
                model=row["model"],
                source=row["source"],
                endpoint=row["endpoint"],
                task_id=row["task_id"],
                prompt_preview=row["prompt_preview"] or "",
                response_preview=row["response_preview"] or "",
                status=row["status"],
                error_code=row["error_code"] or "",
                error_message=row["error_message"] or "",
                latency_ms=row["latency_ms"],
                request_tokens=row["request_tokens"],
                response_tokens=row["response_tokens"],
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def list_by_created_range(self, start_at: datetime, end_at: datetime) -> List[AICallLog]:
        rows = self.db.fetchall(
            """
            SELECT * FROM ai_call_logs
            WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at ASC
            """,
            (start_at.isoformat(), end_at.isoformat()),
        )
        return [
            AICallLog(
                call_id=row["call_id"],
                provider_name=row["provider_name"],
                model=row["model"],
                source=row["source"],
                endpoint=row["endpoint"],
                task_id=row["task_id"],
                prompt_preview=row["prompt_preview"] or "",
                response_preview=row["response_preview"] or "",
                status=row["status"],
                error_code=row["error_code"] or "",
                error_message=row["error_message"] or "",
                latency_ms=row["latency_ms"],
                request_tokens=row["request_tokens"],
                response_tokens=row["response_tokens"],
                created_at=parse_utc_datetime(row["created_at"]),
            )
            for row in rows
        ]


class UsageMetricsDailyRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def upsert(self, record: UsageMetricsDailyRecord) -> UsageMetricsDailyRecord:
        self.db.execute(
            """
            INSERT OR REPLACE INTO usage_metrics_daily (
                metric_date, service_key, model, provider_name,
                ai_call_total, ai_error_count, ai_success_count,
                ai_avg_latency_ms, ai_total_tokens, ai_total_cost,
                ai_timeout_count, guardrail_fallback_count, guardrail_retried_count, guardrail_schema_error_count,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.metric_date,
                record.service_key,
                record.model,
                record.provider_name,
                record.ai_call_total,
                record.ai_error_count,
                record.ai_success_count,
                record.ai_avg_latency_ms,
                record.ai_total_tokens,
                record.ai_total_cost,
                record.ai_timeout_count,
                record.guardrail_fallback_count,
                record.guardrail_retried_count,
                record.guardrail_schema_error_count,
                record.updated_at.isoformat(),
            ),
        )
        return record

    def list(
        self,
        start_date: str,
        end_date: str,
        service_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[UsageMetricsDailyRecord]:
        clauses = ["metric_date >= ?", "metric_date <= ?"]
        params: List[Any] = [start_date, end_date]

        if service_key:
            clauses.append("service_key = ?")
            params.append(service_key)
        if model:
            clauses.append("model = ?")
            params.append(model)

        rows = self.db.fetchall(
            f"""
            SELECT * FROM usage_metrics_daily
            WHERE {' AND '.join(clauses)}
            ORDER BY metric_date ASC, service_key ASC, model ASC, provider_name ASC
            """,
            params,
        )
        return [
            UsageMetricsDailyRecord(
                metric_date=row["metric_date"],
                service_key=row["service_key"],
                model=row["model"],
                provider_name=row["provider_name"],
                ai_call_total=int(row["ai_call_total"]),
                ai_error_count=int(row["ai_error_count"]),
                ai_success_count=int(row["ai_success_count"]),
                ai_avg_latency_ms=float(row["ai_avg_latency_ms"]),
                ai_total_tokens=int(row["ai_total_tokens"]),
                ai_total_cost=float(row["ai_total_cost"]),
                ai_timeout_count=int(row["ai_timeout_count"] or 0),
                guardrail_fallback_count=int(row["guardrail_fallback_count"] or 0),
                guardrail_retried_count=int(row["guardrail_retried_count"] or 0),
                guardrail_schema_error_count=int(row["guardrail_schema_error_count"] or 0),
                updated_at=parse_utc_datetime(row["updated_at"]),
            )
            for row in rows
        ]


class AIProviderConfigRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    @staticmethod
    def _from_row(row) -> AIProviderConfigRecord:
        return AIProviderConfigRecord(
            provider_id=row["provider_id"],
            name=row["name"],
            provider_type=row["provider_type"],
            model=row["model"],
            base_url=row["base_url"],
            api_key=row["api_key"] or "",
            enabled=bool(row["enabled"]),
            is_default=bool(row["is_default"]),
            timeout=row["timeout"],
            max_retries=row["max_retries"],
            created_at=parse_utc_datetime(row["created_at"]),
            updated_at=parse_utc_datetime(row["updated_at"]),
        )

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(1) AS count FROM ai_provider_configs")
        return int(row["count"]) if row else 0

    def get(self, provider_id: str) -> Optional[AIProviderConfigRecord]:
        row = self.db.fetchone("SELECT * FROM ai_provider_configs WHERE provider_id = ?", (provider_id,))
        if not row:
            return None
        return self._from_row(row)

    def get_by_name(self, name: str) -> Optional[AIProviderConfigRecord]:
        row = self.db.fetchone("SELECT * FROM ai_provider_configs WHERE name = ?", (name,))
        if not row:
            return None
        return self._from_row(row)

    def get_default(self) -> Optional[AIProviderConfigRecord]:
        row = self.db.fetchone(
            "SELECT * FROM ai_provider_configs WHERE is_default = 1 ORDER BY updated_at DESC LIMIT 1"
        )
        if not row:
            return None
        return self._from_row(row)

    def list(self, enabled_only: bool = False) -> List[AIProviderConfigRecord]:
        where_clause = "WHERE enabled = 1" if enabled_only else ""
        rows = self.db.fetchall(
            f"SELECT * FROM ai_provider_configs {where_clause} ORDER BY is_default DESC, name ASC"
        )
        return [self._from_row(row) for row in rows]

    def save(self, record: AIProviderConfigRecord) -> AIProviderConfigRecord:
        now = utc_now_iso()
        is_default = 1 if record.is_default else 0
        if is_default:
            self.db.execute("UPDATE ai_provider_configs SET is_default = 0")

        self.db.execute(
            """
            INSERT OR REPLACE INTO ai_provider_configs (
                provider_id, name, provider_type, model, base_url, api_key,
                enabled, is_default, timeout, max_retries, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.provider_id,
                record.name,
                record.provider_type,
                record.model,
                record.base_url,
                record.api_key,
                1 if record.enabled else 0,
                is_default,
                record.timeout,
                record.max_retries,
                record.created_at.isoformat(),
                now,
            ),
        )
        latest = self.get(record.provider_id)
        return latest if latest else record

    def update(self, provider_id: str, updates: dict[str, Any]) -> Optional[AIProviderConfigRecord]:
        current = self.get(provider_id)
        if not current:
            return None

        merged = current.model_copy(update=updates)
        merged.updated_at = utc_now()
        return self.save(merged)

    def set_default(self, provider_id: str) -> Optional[AIProviderConfigRecord]:
        current = self.get(provider_id)
        if not current:
            return None
        if not current.enabled:
            return None
        self.db.execute("UPDATE ai_provider_configs SET is_default = 0")
        self.db.execute(
            "UPDATE ai_provider_configs SET is_default = 1, updated_at = ? WHERE provider_id = ?",
            (utc_now_iso(), provider_id),
        )
        return self.get(provider_id)

    def delete(self, provider_id: str) -> bool:
        current = self.get(provider_id)
        if not current:
            return False
        self.db.execute("DELETE FROM ai_provider_configs WHERE provider_id = ?", (provider_id,))
        if current.is_default:
            fallback = self.db.fetchone(
                "SELECT provider_id FROM ai_provider_configs WHERE enabled = 1 ORDER BY updated_at DESC LIMIT 1"
            )
            if fallback:
                self.set_default(str(fallback["provider_id"]))
        return True


class AnalysisSessionRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, session: AnalysisSession) -> AnalysisSession:
        self.db.execute(
            """
            INSERT OR REPLACE INTO analysis_sessions (
                session_id, source, title, prompt, service_key, time_range,
                incident_id, recommendation_id, evidence_ids_json, executor_result_ids_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.source.value,
                session.title,
                session.prompt,
                session.service_key,
                session.time_range,
                session.incident_id,
                session.recommendation_id,
                _to_json(session.evidence_ids),
                _to_json(session.executor_result_ids),
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
            ),
        )
        latest = self.get(session.session_id)
        return latest if latest else session

    def get(self, session_id: str) -> Optional[AnalysisSession]:
        row = self.db.fetchone("SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,))
        if not row:
            return None
        return AnalysisSession(
            session_id=row["session_id"],
            source=row["source"],
            title=row["title"] or "",
            prompt=row["prompt"] or "",
            service_key=row["service_key"] or "",
            time_range=row["time_range"] or "1h",
            incident_id=row["incident_id"],
            recommendation_id=row["recommendation_id"],
            evidence_ids=_from_json(row["evidence_ids_json"], []),
            executor_result_ids=_from_json(row["executor_result_ids_json"], []),
            created_at=parse_utc_datetime(row["created_at"]),
            updated_at=parse_utc_datetime(row["updated_at"]),
        )

    def update(self, session_id: str, updates: dict[str, Any]) -> Optional[AnalysisSession]:
        current = self.get(session_id)
        if not current:
            return None
        merged = current.model_copy(update=updates)
        merged.updated_at = utc_now()
        return self.save(merged)


class AIWritebackRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, record: AIWritebackRecord) -> AIWritebackRecord:
        self.db.execute(
            """
            INSERT OR REPLACE INTO ai_writebacks (
                writeback_id, session_id, kind, title, summary, content, provider, status,
                source, incident_id, recommendation_id, task_id, claims_json,
                command_suggestions_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.writeback_id,
                record.session_id,
                record.kind.value,
                record.title,
                record.summary,
                record.content,
                record.provider,
                record.status,
                record.source,
                record.incident_id,
                record.recommendation_id,
                record.task_id,
                _to_json(record.claims),
                _to_json(record.command_suggestions),
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )
        latest = self.get(record.writeback_id)
        return latest if latest else record

    def _from_row(self, row) -> AIWritebackRecord:
        return AIWritebackRecord(
            writeback_id=row["writeback_id"],
            session_id=row["session_id"],
            kind=row["kind"],
            title=row["title"] or "",
            summary=row["summary"] or "",
            content=row["content"] or "",
            provider=row["provider"] or "",
            status=row["status"] or "success",
            source=row["source"] or "ai_assistant",
            incident_id=row["incident_id"],
            recommendation_id=row["recommendation_id"],
            task_id=row["task_id"],
            claims=_from_json(row["claims_json"], []),
            command_suggestions=_from_json(row["command_suggestions_json"], []),
            created_at=parse_utc_datetime(row["created_at"]),
            updated_at=parse_utc_datetime(row["updated_at"]),
        )

    def get(self, writeback_id: str) -> Optional[AIWritebackRecord]:
        row = self.db.fetchone("SELECT * FROM ai_writebacks WHERE writeback_id = ?", (writeback_id,))
        if not row:
            return None
        return self._from_row(row)

    def list_by_session(self, session_id: str, limit: int = 50) -> List[AIWritebackRecord]:
        safe_limit = max(1, min(limit, 200))
        rows = self.db.fetchall(
            """
            SELECT * FROM ai_writebacks
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, safe_limit),
        )
        return [self._from_row(row) for row in rows]

    def list_by_incident(self, incident_id: str, limit: int = 50) -> List[AIWritebackRecord]:
        safe_limit = max(1, min(limit, 200))
        rows = self.db.fetchall(
            """
            SELECT * FROM ai_writebacks
            WHERE incident_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (incident_id, safe_limit),
        )
        return [self._from_row(row) for row in rows]

    def list_by_recommendation(self, recommendation_id: str, limit: int = 50) -> List[AIWritebackRecord]:
        safe_limit = max(1, min(limit, 200))
        rows = self.db.fetchall(
            """
            SELECT * FROM ai_writebacks
            WHERE recommendation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (recommendation_id, safe_limit),
        )
        return [self._from_row(row) for row in rows]

    def list_by_task(self, task_id: str, limit: int = 50) -> List[AIWritebackRecord]:
        safe_limit = max(1, min(limit, 200))
        rows = self.db.fetchall(
            """
            SELECT * FROM ai_writebacks
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (task_id, safe_limit),
        )
        return [self._from_row(row) for row in rows]


class ExecutorPluginRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    @staticmethod
    def _from_row(row) -> ExecutorPluginRecord:
        return ExecutorPluginRecord(
            plugin_key=row["plugin_key"],
            display_name=row["display_name"],
            description=row["description"] or "",
            enabled=bool(row["enabled"]),
            readonly_only=bool(row["readonly_only"]),
            write_enabled=bool(row["write_enabled"]),
            failure_count=int(row["failure_count"] or 0),
            circuit_open_until=_parse_dt(row["circuit_open_until"]),
            last_error=row["last_error"] or "",
            updated_at=parse_utc_datetime(row["updated_at"]),
        )

    def list(self) -> List[ExecutorPluginRecord]:
        rows = self.db.fetchall("SELECT * FROM executor_plugins ORDER BY plugin_key ASC")
        return [self._from_row(row) for row in rows]

    def get(self, plugin_key: str) -> Optional[ExecutorPluginRecord]:
        row = self.db.fetchone("SELECT * FROM executor_plugins WHERE plugin_key = ?", (plugin_key,))
        if not row:
            return None
        return self._from_row(row)

    def save(self, record: ExecutorPluginRecord) -> ExecutorPluginRecord:
        self.db.execute(
            """
            INSERT OR REPLACE INTO executor_plugins (
                plugin_key, display_name, description, enabled, readonly_only,
                write_enabled, failure_count, circuit_open_until, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.plugin_key,
                record.display_name,
                record.description,
                1 if record.enabled else 0,
                1 if record.readonly_only else 0,
                1 if record.write_enabled else 0,
                record.failure_count,
                record.circuit_open_until.isoformat() if record.circuit_open_until else None,
                record.last_error,
                record.updated_at.isoformat(),
            ),
        )
        latest = self.get(record.plugin_key)
        return latest if latest else record

    def ensure_seed(self, defaults: List[ExecutorPluginRecord]) -> None:
        for item in defaults:
            current = self.get(item.plugin_key)
            if current:
                continue
            self.save(item)

    def update(self, plugin_key: str, updates: dict[str, Any]) -> Optional[ExecutorPluginRecord]:
        current = self.get(plugin_key)
        if not current:
            return None
        merged = current.model_copy(update=updates)
        merged.updated_at = utc_now()
        return self.save(merged)


class ExecutorAuditLogRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    @staticmethod
    def _from_row(row) -> ExecutorAuditRecord:
        return ExecutorAuditRecord(
            execution_id=row["execution_id"],
            task_id=row["task_id"],
            plugin_key=row["plugin_key"],
            command=row["command"],
            readonly=bool(row["readonly"]),
            status=row["status"],
            exit_code=row["exit_code"],
            stdout_preview=row["stdout_preview"] or "",
            stderr_preview=row["stderr_preview"] or "",
            duration_ms=int(row["duration_ms"] or 0),
            error_code=row["error_code"] or "",
            error_message=row["error_message"] or "",
            operator=row["operator"] or "system",
            approval_ticket=row["approval_ticket"] or "",
            created_at=parse_utc_datetime(row["created_at"]),
        )

    def save(self, item: ExecutorAuditRecord) -> ExecutorAuditRecord:
        self.db.execute(
            """
            INSERT OR REPLACE INTO executor_audit_logs (
                execution_id, task_id, plugin_key, command, readonly,
                status, exit_code, stdout_preview, stderr_preview, duration_ms,
                error_code, error_message, operator, approval_ticket, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.execution_id,
                item.task_id,
                item.plugin_key,
                item.command,
                1 if item.readonly else 0,
                item.status.value,
                item.exit_code,
                item.stdout_preview,
                item.stderr_preview,
                item.duration_ms,
                item.error_code,
                item.error_message,
                item.operator,
                item.approval_ticket,
                item.created_at.isoformat(),
            ),
        )
        latest = self.get(item.execution_id)
        return latest if latest else item

    def get(self, execution_id: str) -> Optional[ExecutorAuditRecord]:
        row = self.db.fetchone(
            "SELECT * FROM executor_audit_logs WHERE execution_id = ?",
            (execution_id,),
        )
        if not row:
            return None
        return self._from_row(row)

    def list(
        self,
        limit: int = 100,
        plugin_key: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ExecutorAuditRecord]:
        safe_limit = max(1, min(limit, 500))
        clauses = []
        params: List[Any] = []
        if plugin_key:
            clauses.append("plugin_key = ?")
            params.append(plugin_key)
        if status:
            clauses.append("status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.fetchall(
            f"SELECT * FROM executor_audit_logs {where_clause} ORDER BY created_at DESC LIMIT ?",
            [*params, safe_limit],
        )
        return [self._from_row(row) for row in rows]

    def list_failures(self, limit: int = 100) -> List[ExecutorAuditRecord]:
        safe_limit = max(1, min(limit, 500))
        rows = self.db.fetchall(
            """
            SELECT * FROM executor_audit_logs
            WHERE status != ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (ExecutorRunStatus.SUCCESS.value, safe_limit),
        )
        return [self._from_row(row) for row in rows]
