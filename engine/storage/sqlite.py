"""
SQLite 持久化底座。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional


class SQLiteDatabase:
    """SQLite 数据库封装。"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[sqlite3.Connection] = None

    @property
    def connection(self) -> sqlite3.Connection:
        """惰性初始化数据库连接。"""
        if self._connection is None:
            self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def initialize(self) -> None:
        """初始化数据库 schema。"""
        cursor = self.connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                progress INTEGER NOT NULL,
                progress_message TEXT,
                trace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                result_ref_json TEXT,
                error_json TEXT,
                approval_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                preview TEXT,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                asset_type TEXT NOT NULL,
                name TEXT NOT NULL,
                namespace TEXT,
                service_key TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                source_refs_json TEXT NOT NULL,
                health_status TEXT NOT NULL,
                unmapped INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                signal_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                asset_id TEXT,
                service_key TEXT NOT NULL,
                severity TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                time_window_start TEXT NOT NULL,
                time_window_end TEXT NOT NULL,
                service_key TEXT NOT NULL,
                related_asset_ids_json TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                confidence REAL NOT NULL,
                recommended_actions_json TEXT NOT NULL,
                reasoning_tags_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                recommendation_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                target_asset_id TEXT,
                kind TEXT NOT NULL,
                confidence REAL NOT NULL,
                observation TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                risk_note TEXT NOT NULL,
                artifact_refs_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                feedback_id TEXT PRIMARY KEY,
                recommendation_id TEXT NOT NULL,
                incident_id TEXT NOT NULL,
                task_id TEXT,
                action TEXT NOT NULL,
                reason_code TEXT,
                comment TEXT,
                operator TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_call_logs (
                call_id TEXT PRIMARY KEY,
                provider_name TEXT NOT NULL,
                model TEXT NOT NULL,
                source TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                task_id TEXT,
                prompt_preview TEXT,
                response_preview TEXT,
                status TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                latency_ms INTEGER NOT NULL,
                request_tokens INTEGER,
                response_tokens INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_provider_configs (
                provider_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                provider_type TEXT NOT NULL,
                model TEXT NOT NULL,
                base_url TEXT,
                api_key TEXT,
                enabled INTEGER NOT NULL,
                is_default INTEGER NOT NULL,
                timeout INTEGER NOT NULL,
                max_retries INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_recommendation ON recommendation_feedback(recommendation_id);
            CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_incident ON recommendation_feedback(incident_id);
            CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_created_at ON recommendation_feedback(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_ai_call_logs_created_at ON ai_call_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ai_call_logs_provider ON ai_call_logs(provider_name);
            CREATE INDEX IF NOT EXISTS idx_ai_provider_configs_default ON ai_provider_configs(is_default);
            """
        )
        self._ensure_column('tasks', 'approval_json', 'TEXT')
        self._ensure_column('ai_call_logs', 'error_code', 'TEXT')
        self._ensure_column('ai_provider_configs', 'is_default', 'INTEGER NOT NULL DEFAULT 0')
        self.connection.commit()

    def _ensure_column(self, table_name: str, column_name: str, definition: str) -> None:
        """为已有数据库补齐新增字段。"""
        rows = self.connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {row['name'] for row in rows}
        if column_name not in columns:
            self.connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def execute(self, query: str, params: Iterable[Any] = ()) -> None:
        """执行写操作。"""
        self.connection.execute(query, tuple(params))
        self.connection.commit()

    def fetchone(self, query: str, params: Iterable[Any] = ()):
        """查询单行。"""
        return self.connection.execute(query, tuple(params)).fetchone()

    def fetchall(self, query: str, params: Iterable[Any] = ()):
        """查询多行。"""
        return list(self.connection.execute(query, tuple(params)).fetchall())
