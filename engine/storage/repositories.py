"""
SQLite repositories。

统一封装各类核心实体的读写，避免业务层拼接 SQL。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from engine.runtime.models import AICallLog, ArtifactRef, Asset, Incident, Recommendation, Signal, TaskApproval, TaskError, TaskRecord

from .sqlite import SQLiteDatabase


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


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
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
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
            created_at=datetime.fromisoformat(row["created_at"]),
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
                created_at=datetime.fromisoformat(row["created_at"]),
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
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
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
            time_window_start=datetime.fromisoformat(row["time_window_start"]),
            time_window_end=datetime.fromisoformat(row["time_window_end"]),
            service_key=row["service_key"],
            related_asset_ids=_from_json(row["related_asset_ids_json"], []),
            evidence_refs=_from_json(row["evidence_refs_json"], []),
            summary=row["summary"],
            confidence=row["confidence"],
            recommended_actions=_from_json(row["recommended_actions_json"], []),
            reasoning_tags=_from_json(row["reasoning_tags_json"], []),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
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
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_by_incident(self, incident_id: str) -> List[Recommendation]:
        rows = self.db.fetchall("SELECT recommendation_id FROM recommendations WHERE incident_id = ? ORDER BY created_at DESC", (incident_id,))
        items: List[Recommendation] = []
        for row in rows:
            recommendation = self.get(row["recommendation_id"])
            if recommendation:
                items.append(recommendation)
        return items


class AICallLogRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def save(self, call_log: AICallLog) -> AICallLog:
        self.db.execute(
            """
            INSERT OR REPLACE INTO ai_call_logs (
                call_id, provider_name, model, source, endpoint, task_id,
                prompt_preview, response_preview, status, error_message,
                latency_ms, request_tokens, response_tokens, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                error_message=row["error_message"] or "",
                latency_ms=row["latency_ms"],
                request_tokens=row["request_tokens"],
                response_tokens=row["response_tokens"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
