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
            """
        )
        self._ensure_column('tasks', 'approval_json', 'TEXT')
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
