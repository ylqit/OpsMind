"""执行插件服务。"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

from engine.runtime.models import (
    ExecutorAuditRecord,
    ExecutorHealthStatus,
    ExecutorPluginKey,
    ExecutorPluginRecord,
    ExecutorRunStatus,
)
from engine.storage.repositories import ExecutorAuditLogRepository, ExecutorPluginRepository


@dataclass(frozen=True)
class ExecutorPluginSpec:
    """执行插件的静态定义。"""

    key: str
    display_name: str
    description: str
    readonly_prefixes: tuple[tuple[str, ...], ...]
    write_prefixes: tuple[tuple[str, ...], ...]


class ExecutorService:
    """统一管理 Linux/K8s/Docker 插件执行。"""

    FAILURE_THRESHOLD = 3
    CIRCUIT_COOLDOWN_SECONDS = 120
    DEFAULT_TIMEOUT_SECONDS = 20
    MAX_PREVIEW_CHARS = 4000
    MAX_COMMAND_CHARS = 400

    def __init__(
        self,
        plugin_repository: ExecutorPluginRepository,
        audit_repository: ExecutorAuditLogRepository,
    ) -> None:
        self.plugin_repository = plugin_repository
        self.audit_repository = audit_repository
        self._specs = self._build_plugin_specs()
        self._seed_default_plugins()

    def _build_plugin_specs(self) -> dict[str, ExecutorPluginSpec]:
        return {
            ExecutorPluginKey.LINUX.value: ExecutorPluginSpec(
                key=ExecutorPluginKey.LINUX.value,
                display_name="Linux 执行插件",
                description="采集主机基础状态与诊断信息，只读优先。",
                readonly_prefixes=(
                    ("ps",),
                    ("df", "-h"),
                    ("free", "-m"),
                    ("uptime",),
                    ("ss", "-s"),
                    ("cat", "/proc/loadavg"),
                ),
                write_prefixes=(
                    ("systemctl", "restart"),
                    ("systemctl", "stop"),
                ),
            ),
            ExecutorPluginKey.K8S.value: ExecutorPluginSpec(
                key=ExecutorPluginKey.K8S.value,
                display_name="K8s 执行插件",
                description="通过 kubectl 读取集群状态，写操作入口默认关闭。",
                readonly_prefixes=(
                    ("kubectl", "get"),
                    ("kubectl", "describe"),
                    ("kubectl", "top"),
                    ("kubectl", "logs"),
                    ("kubectl", "cluster-info"),
                ),
                write_prefixes=(
                    ("kubectl", "apply"),
                    ("kubectl", "rollout", "restart"),
                    ("kubectl", "delete"),
                ),
            ),
            ExecutorPluginKey.DOCKER.value: ExecutorPluginSpec(
                key=ExecutorPluginKey.DOCKER.value,
                display_name="Docker 执行插件",
                description="通过 docker CLI 读取容器状态与日志。",
                readonly_prefixes=(
                    ("docker", "ps"),
                    ("docker", "stats", "--no-stream"),
                    ("docker", "inspect"),
                    ("docker", "logs"),
                    ("docker", "images"),
                ),
                write_prefixes=(
                    ("docker", "restart"),
                    ("docker", "stop"),
                    ("docker", "start"),
                ),
            ),
        }

    def _seed_default_plugins(self) -> None:
        defaults = [
            ExecutorPluginRecord(
                plugin_key=spec.key,
                display_name=spec.display_name,
                description=spec.description,
                enabled=True,
                readonly_only=False,
                write_enabled=False,
                failure_count=0,
                circuit_open_until=None,
                last_error="",
            )
            for spec in self._specs.values()
        ]
        self.plugin_repository.ensure_seed(defaults)

    def _safe_preview(self, raw: str) -> str:
        if not raw:
            return ""
        return raw[: self.MAX_PREVIEW_CHARS]

    def _serialize_plugin(self, plugin: ExecutorPluginRecord) -> dict[str, Any]:
        spec = self._specs.get(plugin.plugin_key)
        now = datetime.utcnow()
        circuit_open = bool(plugin.circuit_open_until and plugin.circuit_open_until > now)

        if not plugin.enabled:
            health_status = ExecutorHealthStatus.DISABLED.value
        elif circuit_open:
            health_status = ExecutorHealthStatus.DEGRADED.value
        else:
            health_status = ExecutorHealthStatus.HEALTHY.value

        readonly_examples = [" ".join(item) for item in (spec.readonly_prefixes if spec else tuple())]
        write_examples = [" ".join(item) for item in (spec.write_prefixes if spec else tuple())]

        return {
            "plugin_key": plugin.plugin_key,
            "display_name": plugin.display_name,
            "description": plugin.description,
            "enabled": plugin.enabled,
            "readonly_only": plugin.readonly_only,
            "write_enabled": plugin.write_enabled,
            "failure_count": plugin.failure_count,
            "circuit_open_until": plugin.circuit_open_until.isoformat() if plugin.circuit_open_until else None,
            "circuit_remaining_seconds": max(0, int((plugin.circuit_open_until - now).total_seconds())) if circuit_open else 0,
            "last_error": plugin.last_error,
            "health_status": health_status,
            "readonly_examples": readonly_examples,
            "write_examples": write_examples,
            "updated_at": plugin.updated_at.isoformat(),
        }

    def _serialize_audit(self, item: ExecutorAuditRecord) -> dict[str, Any]:
        return {
            "execution_id": item.execution_id,
            "task_id": item.task_id,
            "plugin_key": item.plugin_key,
            "command": item.command,
            "readonly": item.readonly,
            "status": item.status.value,
            "exit_code": item.exit_code,
            "stdout_preview": item.stdout_preview,
            "stderr_preview": item.stderr_preview,
            "duration_ms": item.duration_ms,
            "error_code": item.error_code,
            "error_message": item.error_message,
            "operator": item.operator,
            "approval_ticket": item.approval_ticket,
            "created_at": item.created_at.isoformat(),
        }

    def get_status(self, recent_limit: int = 30) -> dict[str, Any]:
        plugins = [self._serialize_plugin(item) for item in self.plugin_repository.list()]
        recent_logs = [self._serialize_audit(item) for item in self.audit_repository.list(limit=recent_limit)]
        return {
            "plugins": plugins,
            "recent_logs": recent_logs,
            "summary": {
                "total": len(plugins),
                "enabled": sum(1 for item in plugins if item["enabled"]),
                "degraded": sum(1 for item in plugins if item["health_status"] == ExecutorHealthStatus.DEGRADED.value),
            },
        }

    def update_plugin(
        self,
        plugin_key: str,
        enabled: bool | None = None,
        write_enabled: bool | None = None,
        approval_ticket: str = "",
    ) -> dict[str, Any]:
        plugin = self.plugin_repository.get(plugin_key)
        if not plugin:
            raise ValueError("插件不存在")

        updates: dict[str, Any] = {}
        if enabled is not None:
            updates["enabled"] = enabled
        if write_enabled is not None:
            if write_enabled and not approval_ticket.strip():
                raise ValueError("启用写操作必须提供 approval_ticket")
            updates["write_enabled"] = write_enabled

        if not updates:
            return self._serialize_plugin(plugin)

        # 重新启用插件时自动清空熔断态，避免人工多次操作。
        if updates.get("enabled") is True:
            updates["failure_count"] = 0
            updates["circuit_open_until"] = None
            updates["last_error"] = ""

        latest = self.plugin_repository.update(plugin_key, updates)
        if not latest:
            raise ValueError("插件更新失败")
        return self._serialize_plugin(latest)

    def _match_prefix(self, tokens: Sequence[str], prefixes: Sequence[Sequence[str]]) -> bool:
        for prefix in prefixes:
            if len(tokens) < len(prefix):
                continue
            if list(tokens[: len(prefix)]) == list(prefix):
                return True
        return False

    def _validate_command(
        self,
        plugin: ExecutorPluginRecord,
        spec: ExecutorPluginSpec,
        command: str,
        readonly: bool,
        approval_ticket: str,
    ) -> tuple[list[str] | None, str | None, str | None]:
        normalized = (command or "").strip()
        if not normalized:
            return None, "EXECUTOR_EMPTY_COMMAND", "命令不能为空"
        if len(normalized) > self.MAX_COMMAND_CHARS:
            return None, "EXECUTOR_COMMAND_TOO_LONG", "命令长度超出限制"

        try:
            tokens = shlex.split(normalized)
        except ValueError:
            return None, "EXECUTOR_COMMAND_PARSE_ERROR", "命令格式不合法"

        if not tokens:
            return None, "EXECUTOR_EMPTY_COMMAND", "命令不能为空"

        if readonly:
            if not self._match_prefix(tokens, spec.readonly_prefixes):
                return None, "EXECUTOR_COMMAND_NOT_ALLOWED", "命令不在只读白名单中"
            return tokens, None, None

        if plugin.readonly_only:
            return None, "EXECUTOR_WRITE_DISABLED", "当前插件仅支持只读执行"
        if not plugin.write_enabled:
            return None, "EXECUTOR_WRITE_DISABLED", "写操作入口未启用"
        if not approval_ticket.strip():
            return None, "EXECUTOR_APPROVAL_REQUIRED", "写操作必须提供 approval_ticket"
        if not self._match_prefix(tokens, spec.write_prefixes):
            return None, "EXECUTOR_COMMAND_NOT_ALLOWED", "命令不在写操作白名单中"

        return tokens, None, None

    def _build_audit(
        self,
        plugin_key: str,
        command: str,
        readonly: bool,
        status: ExecutorRunStatus,
        operator: str,
        approval_ticket: str,
        duration_ms: int = 0,
        task_id: str | None = None,
        exit_code: int | None = None,
        stdout_preview: str = "",
        stderr_preview: str = "",
        error_code: str = "",
        error_message: str = "",
    ) -> ExecutorAuditRecord:
        return ExecutorAuditRecord(
            task_id=task_id,
            plugin_key=plugin_key,
            command=command,
            readonly=readonly,
            status=status,
            exit_code=exit_code,
            stdout_preview=self._safe_preview(stdout_preview),
            stderr_preview=self._safe_preview(stderr_preview),
            duration_ms=max(0, duration_ms),
            error_code=error_code,
            error_message=error_message,
            operator=operator or "system",
            approval_ticket=approval_ticket,
        )

    def _apply_failure_state(self, plugin: ExecutorPluginRecord, error_text: str) -> ExecutorPluginRecord:
        failure_count = plugin.failure_count + 1
        updates: dict[str, Any] = {
            "failure_count": failure_count,
            "last_error": error_text[:300],
        }
        if failure_count >= self.FAILURE_THRESHOLD:
            updates["circuit_open_until"] = datetime.utcnow() + timedelta(seconds=self.CIRCUIT_COOLDOWN_SECONDS)
        latest = self.plugin_repository.update(plugin.plugin_key, updates)
        return latest if latest else plugin

    def _reset_failure_state(self, plugin: ExecutorPluginRecord) -> ExecutorPluginRecord:
        latest = self.plugin_repository.update(
            plugin.plugin_key,
            {
                "failure_count": 0,
                "circuit_open_until": None,
                "last_error": "",
            },
        )
        return latest if latest else plugin

    def run(
        self,
        plugin_key: str,
        command: str,
        readonly: bool = True,
        timeout_seconds: int | None = None,
        task_id: str | None = None,
        operator: str = "system",
        approval_ticket: str = "",
    ) -> dict[str, Any]:
        plugin = self.plugin_repository.get(plugin_key)
        if not plugin:
            raise ValueError("插件不存在")

        spec = self._specs.get(plugin_key)
        if not spec:
            raise ValueError("插件规格未注册")

        if not plugin.enabled:
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.REJECTED,
                operator=operator,
                approval_ticket=approval_ticket,
                error_code="EXECUTOR_PLUGIN_DISABLED",
                error_message="插件未启用",
                task_id=task_id,
            )
            saved = self.audit_repository.save(audit)
            return {
                "execution": self._serialize_audit(saved),
                "plugin": self._serialize_plugin(plugin),
            }

        now = datetime.utcnow()
        if plugin.circuit_open_until and plugin.circuit_open_until > now:
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.CIRCUIT_OPEN,
                operator=operator,
                approval_ticket=approval_ticket,
                error_code="EXECUTOR_CIRCUIT_OPEN",
                error_message="插件熔断中，请稍后重试",
                task_id=task_id,
            )
            saved = self.audit_repository.save(audit)
            return {
                "execution": self._serialize_audit(saved),
                "plugin": self._serialize_plugin(plugin),
            }

        tokens, error_code, error_message = self._validate_command(
            plugin=plugin,
            spec=spec,
            command=command,
            readonly=readonly,
            approval_ticket=approval_ticket,
        )
        if error_code or not tokens:
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.REJECTED,
                operator=operator,
                approval_ticket=approval_ticket,
                error_code=error_code or "EXECUTOR_VALIDATE_ERROR",
                error_message=error_message or "命令校验失败",
                task_id=task_id,
            )
            saved = self.audit_repository.save(audit)
            return {
                "execution": self._serialize_audit(saved),
                "plugin": self._serialize_plugin(plugin),
            }

        timeout_value = max(1, min(timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS, 120))
        started = time.perf_counter()

        try:
            result = subprocess.run(
                tokens,
                capture_output=True,
                text=True,
                timeout=timeout_value,
                check=False,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            if result.returncode == 0:
                audit = self._build_audit(
                    plugin_key=plugin_key,
                    command=command,
                    readonly=readonly,
                    status=ExecutorRunStatus.SUCCESS,
                    operator=operator,
                    approval_ticket=approval_ticket,
                    duration_ms=duration_ms,
                    task_id=task_id,
                    exit_code=0,
                    stdout_preview=result.stdout,
                    stderr_preview=result.stderr,
                )
                saved = self.audit_repository.save(audit)
                plugin = self._reset_failure_state(plugin)
                return {
                    "execution": self._serialize_audit(saved),
                    "plugin": self._serialize_plugin(plugin),
                }

            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.ERROR,
                operator=operator,
                approval_ticket=approval_ticket,
                duration_ms=duration_ms,
                task_id=task_id,
                exit_code=result.returncode,
                stdout_preview=result.stdout,
                stderr_preview=result.stderr,
                error_code="EXECUTOR_EXIT_NON_ZERO",
                error_message="命令返回非 0 退出码",
            )
            saved = self.audit_repository.save(audit)
            plugin = self._apply_failure_state(plugin, saved.error_message or "命令执行失败")
            return {
                "execution": self._serialize_audit(saved),
                "plugin": self._serialize_plugin(plugin),
            }
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.TIMEOUT,
                operator=operator,
                approval_ticket=approval_ticket,
                duration_ms=duration_ms,
                task_id=task_id,
                stdout_preview=str(exc.stdout or ""),
                stderr_preview=str(exc.stderr or ""),
                error_code="EXECUTOR_TIMEOUT",
                error_message="命令执行超时",
            )
            saved = self.audit_repository.save(audit)
            plugin = self._apply_failure_state(plugin, "命令执行超时")
            return {
                "execution": self._serialize_audit(saved),
                "plugin": self._serialize_plugin(plugin),
            }
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.ERROR,
                operator=operator,
                approval_ticket=approval_ticket,
                duration_ms=duration_ms,
                task_id=task_id,
                error_code="EXECUTOR_RUNTIME_ERROR",
                error_message=str(exc),
            )
            saved = self.audit_repository.save(audit)
            plugin = self._apply_failure_state(plugin, str(exc))
            return {
                "execution": self._serialize_audit(saved),
                "plugin": self._serialize_plugin(plugin),
            }
