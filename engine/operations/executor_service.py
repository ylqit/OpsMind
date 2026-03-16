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
    readonly_command_packs: tuple["ReadonlyCommandPackItem", ...]


@dataclass(frozen=True)
class ReadonlyCommandPackItem:
    """只读命令包模板。"""

    template_id: str
    category_key: str
    category_label: str
    title: str
    description: str
    command: str


@dataclass(frozen=True)
class ExecutorRunContext:
    """执行上下文：当前默认本地执行，远程模式仅保留接口。"""

    mode: str = "local"
    remote_kind: str = ""
    remote_target: str = ""
    remote_namespace: str = ""

    def to_dict(self, remote_enabled: bool) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "remote_kind": self.remote_kind,
            "remote_target": self.remote_target,
            "remote_namespace": self.remote_namespace,
            "remote_enabled": remote_enabled,
        }


class ExecutorService:
    """统一管理 Linux/K8s/Docker 插件执行。"""

    FAILURE_THRESHOLD = 3
    CIRCUIT_COOLDOWN_SECONDS = 120
    DEFAULT_TIMEOUT_SECONDS = 20
    MAX_PREVIEW_CHARS = 4000
    MAX_COMMAND_CHARS = 400
    REMOTE_EXECUTION_ENABLED = False

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
                readonly_command_packs=(
                    ReadonlyCommandPackItem(
                        template_id="linux_proc_top",
                        category_key="process",
                        category_label="进程",
                        title="进程快照",
                        description="查看当前主机进程概况",
                        command="ps aux",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="linux_disk_usage",
                        category_key="storage",
                        category_label="存储",
                        title="磁盘使用率",
                        description="查看各挂载点磁盘占用情况",
                        command="df -h",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="linux_memory_usage",
                        category_key="memory",
                        category_label="内存",
                        title="内存概览",
                        description="查看内存和 swap 使用情况",
                        command="free -m",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="linux_load",
                        category_key="load",
                        category_label="负载",
                        title="系统负载",
                        description="查看系统 uptime 与负载信息",
                        command="uptime",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="linux_socket_summary",
                        category_key="network",
                        category_label="网络",
                        title="套接字摘要",
                        description="查看网络连接状态统计",
                        command="ss -s",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="linux_proc_loadavg",
                        category_key="load",
                        category_label="负载",
                        title="Loadavg 原始值",
                        description="读取 /proc/loadavg 用于任务诊断附证",
                        command="cat /proc/loadavg",
                    ),
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
                readonly_command_packs=(
                    ReadonlyCommandPackItem(
                        template_id="k8s_pods_all",
                        category_key="workload",
                        category_label="工作负载",
                        title="全量 Pod 列表",
                        description="查看所有命名空间 Pod 状态",
                        command="kubectl get pods -A",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="k8s_nodes",
                        category_key="node",
                        category_label="节点",
                        title="节点状态",
                        description="查看节点资源与调度状态",
                        command="kubectl get nodes -o wide",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="k8s_top_pods",
                        category_key="resource",
                        category_label="资源",
                        title="Pod 资源用量",
                        description="查看 Pod CPU/内存实时占用",
                        command="kubectl top pod -A",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="k8s_describe_pod",
                        category_key="diagnosis",
                        category_label="诊断",
                        title="Pod 详情",
                        description="排查 Pod 事件与调度失败原因",
                        command="kubectl describe pod <pod-name> -n <namespace>",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="k8s_pod_logs",
                        category_key="logs",
                        category_label="日志",
                        title="Pod 日志尾部",
                        description="读取容器最近日志片段",
                        command="kubectl logs <pod-name> -n <namespace> --tail=200",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="k8s_cluster_info",
                        category_key="cluster",
                        category_label="集群",
                        title="集群信息",
                        description="查看 API Server 与集群基础信息",
                        command="kubectl cluster-info",
                    ),
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
                readonly_command_packs=(
                    ReadonlyCommandPackItem(
                        template_id="docker_ps",
                        category_key="runtime",
                        category_label="运行态",
                        title="容器列表",
                        description="查看容器运行状态与端口映射",
                        command="docker ps",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="docker_stats",
                        category_key="resource",
                        category_label="资源",
                        title="资源快照",
                        description="查看容器 CPU/内存实时占用",
                        command="docker stats --no-stream",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="docker_inspect",
                        category_key="diagnosis",
                        category_label="诊断",
                        title="容器详情",
                        description="查看容器配置、网络与挂载信息",
                        command="docker inspect <container-id>",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="docker_logs_tail",
                        category_key="logs",
                        category_label="日志",
                        title="容器日志尾部",
                        description="读取容器最近 200 行日志",
                        command="docker logs --tail 200 <container-id>",
                    ),
                    ReadonlyCommandPackItem(
                        template_id="docker_images",
                        category_key="image",
                        category_label="镜像",
                        title="镜像列表",
                        description="查看本机镜像与标签信息",
                        command="docker images",
                    ),
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

    def _build_stderr_summary(self, stderr_preview: str, error_message: str, max_chars: int = 160) -> str:
        text = (stderr_preview or "").strip()
        if text:
            first_non_empty = next((line.strip() for line in text.splitlines() if line.strip()), "")
            candidate = first_non_empty or text
        else:
            candidate = (error_message or "").strip()
        if not candidate:
            return "-"
        if len(candidate) <= max_chars:
            return candidate
        return f"{candidate[: max_chars - 3]}..."

    def _build_recent_failure_item(self, audit_payload: dict[str, Any]) -> dict[str, Any]:
        error_code = str(audit_payload.get("error_code") or "").strip()
        approval_ticket = str(audit_payload.get("approval_ticket") or "").strip()
        stderr_summary = self._build_stderr_summary(
            str(audit_payload.get("stderr_preview") or ""),
            str(audit_payload.get("error_message") or ""),
        )
        # 失败摘要字段直接服务前端表格，避免页面重复拼接规则。
        return {
            **audit_payload,
            "stderr_summary": stderr_summary,
            "approval_required": error_code == "EXECUTOR_APPROVAL_REQUIRED",
            "has_approval_ticket": bool(approval_ticket),
        }

    def _normalize_execution_context(self, execution_context: dict[str, Any] | None) -> ExecutorRunContext:
        raw = execution_context if isinstance(execution_context, dict) else {}
        mode = str(raw.get("mode") or "local").strip().lower()
        if mode not in {"local", "remote"}:
            mode = "local"
        return ExecutorRunContext(
            mode=mode,
            remote_kind=str(raw.get("remote_kind") or "").strip(),
            remote_target=str(raw.get("remote_target") or "").strip(),
            remote_namespace=str(raw.get("remote_namespace") or "").strip(),
        )

    def _build_run_response(
        self,
        audit: ExecutorAuditRecord,
        plugin: ExecutorPluginRecord,
        context: ExecutorRunContext,
    ) -> dict[str, Any]:
        return {
            "execution": self._serialize_audit(audit),
            "plugin": self._serialize_plugin(plugin),
            "execution_context": context.to_dict(remote_enabled=self.REMOTE_EXECUTION_ENABLED),
        }

    def _execute_local_command(self, tokens: Sequence[str], timeout_value: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            tokens,
            capture_output=True,
            text=True,
            timeout=timeout_value,
            check=False,
        )

    def _execute_remote_command(
        self,
        context: ExecutorRunContext,
        tokens: Sequence[str],
        timeout_value: int,
    ) -> subprocess.CompletedProcess:
        # 远程执行抽象层先保留接口，待后续接入具体协议（如 ssh/k8s api）。
        del context, tokens, timeout_value
        raise NotImplementedError("远程执行通道尚未接入")

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
        readonly_command_packs = []
        readonly_categories: list[dict[str, Any]] = []
        category_counter: dict[str, dict[str, Any]] = {}
        if spec:
            for item in spec.readonly_command_packs:
                readonly_command_packs.append(
                    {
                        "template_id": item.template_id,
                        "category_key": item.category_key,
                        "category_label": item.category_label,
                        "title": item.title,
                        "description": item.description,
                        "command": item.command,
                    }
                )
                if item.category_key not in category_counter:
                    category_counter[item.category_key] = {
                        "category_key": item.category_key,
                        "category_label": item.category_label,
                        "count": 0,
                    }
                category_counter[item.category_key]["count"] += 1
            readonly_categories = list(category_counter.values())

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
            "readonly_categories": readonly_categories,
            "readonly_command_packs": readonly_command_packs,
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

    def build_execution_evidence(self, run_result: dict[str, Any]) -> dict[str, Any]:
        execution = run_result.get("execution") if isinstance(run_result.get("execution"), dict) else {}
        plugin = run_result.get("plugin") if isinstance(run_result.get("plugin"), dict) else {}
        # 统一证据快照结构，便于任务中心、异常中心和建议中心复用同一数据契约。
        return {
            "source": "executor_plugin",
            "generated_at": datetime.utcnow().isoformat(),
            "execution": {
                "execution_id": str(execution.get("execution_id") or ""),
                "task_id": str(execution.get("task_id") or ""),
                "plugin_key": str(execution.get("plugin_key") or ""),
                "command": str(execution.get("command") or ""),
                "readonly": bool(execution.get("readonly", True)),
                "status": str(execution.get("status") or ""),
                "exit_code": execution.get("exit_code"),
                "duration_ms": int(execution.get("duration_ms") or 0),
                "error_code": str(execution.get("error_code") or ""),
                "error_message": str(execution.get("error_message") or ""),
                "stdout_preview": str(execution.get("stdout_preview") or ""),
                "stderr_preview": str(execution.get("stderr_preview") or ""),
                "operator": str(execution.get("operator") or ""),
                "approval_ticket": str(execution.get("approval_ticket") or ""),
                "created_at": str(execution.get("created_at") or ""),
            },
            "plugin": {
                "plugin_key": str(plugin.get("plugin_key") or ""),
                "display_name": str(plugin.get("display_name") or ""),
                "health_status": str(plugin.get("health_status") or ""),
                "readonly_only": bool(plugin.get("readonly_only", True)),
                "write_enabled": bool(plugin.get("write_enabled", False)),
            },
        }

    def get_status(self, recent_limit: int = 30) -> dict[str, Any]:
        plugins = [self._serialize_plugin(item) for item in self.plugin_repository.list()]
        safe_recent_limit = max(1, min(recent_limit, 200))
        recent_logs = [self._serialize_audit(item) for item in self.audit_repository.list(limit=safe_recent_limit)]
        failure_logs = [self._serialize_audit(item) for item in self.audit_repository.list_failures(limit=safe_recent_limit)]

        status_counter: dict[str, int] = {
            ExecutorRunStatus.SUCCESS.value: 0,
            ExecutorRunStatus.ERROR.value: 0,
            ExecutorRunStatus.TIMEOUT.value: 0,
            ExecutorRunStatus.REJECTED.value: 0,
            ExecutorRunStatus.CIRCUIT_OPEN.value: 0,
        }
        for item in recent_logs:
            status_key = str(item.get("status") or "")
            if status_key in status_counter:
                status_counter[status_key] += 1

        # 仅返回近期失败样本，前端可直接展示“熔断/审批/stderr”摘要。
        recent_failures = [self._build_recent_failure_item(item) for item in failure_logs[:8]]
        approval_required_count = sum(1 for item in failure_logs if item.get("error_code") == "EXECUTOR_APPROVAL_REQUIRED")
        circuit_plugins = [item for item in plugins if int(item.get("circuit_remaining_seconds") or 0) > 0]

        error_code_counter: dict[str, int] = {}
        for item in failure_logs:
            error_code = str(item.get("error_code") or "").strip() or "UNKNOWN"
            error_code_counter[error_code] = error_code_counter.get(error_code, 0) + 1
        top_error_codes = [
            {"error_code": key, "count": value}
            for key, value in sorted(error_code_counter.items(), key=lambda pair: pair[1], reverse=True)[:5]
        ]

        return {
            "plugins": plugins,
            "recent_logs": recent_logs,
            "recent_failures": recent_failures,
            "summary": {
                "total": len(plugins),
                "enabled": sum(1 for item in plugins if item["enabled"]),
                "degraded": sum(1 for item in plugins if item["health_status"] == ExecutorHealthStatus.DEGRADED.value),
                "success": status_counter[ExecutorRunStatus.SUCCESS.value],
                "error": status_counter[ExecutorRunStatus.ERROR.value],
                "timeout": status_counter[ExecutorRunStatus.TIMEOUT.value],
                "rejected": status_counter[ExecutorRunStatus.REJECTED.value],
                "circuit_open": status_counter[ExecutorRunStatus.CIRCUIT_OPEN.value],
                "approval_required": approval_required_count,
                "circuit_open_plugins": len(circuit_plugins),
                "top_error_codes": top_error_codes,
            },
            "recent_limit": safe_recent_limit,
        }

    def list_readonly_command_packs(self, plugin_key: str | None = None) -> dict[str, Any]:
        # 命令包单独输出，前端可在不加载审计日志的情况下做模板展示与快速填充。
        if plugin_key:
            plugin = self.plugin_repository.get(plugin_key)
            if not plugin:
                raise ValueError("插件不存在")
            serialized = self._serialize_plugin(plugin)
            return {
                "items": [
                    {
                        "plugin_key": serialized["plugin_key"],
                        "display_name": serialized["display_name"],
                        "readonly_categories": serialized["readonly_categories"],
                        "readonly_command_packs": serialized["readonly_command_packs"],
                    }
                ],
                "total": 1,
            }

        items = []
        for plugin in self.plugin_repository.list():
            serialized = self._serialize_plugin(plugin)
            items.append(
                {
                    "plugin_key": serialized["plugin_key"],
                    "display_name": serialized["display_name"],
                    "readonly_categories": serialized["readonly_categories"],
                    "readonly_command_packs": serialized["readonly_command_packs"],
                }
            )
        return {
            "items": items,
            "total": len(items),
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
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plugin = self.plugin_repository.get(plugin_key)
        if not plugin:
            raise ValueError("插件不存在")

        spec = self._specs.get(plugin_key)
        if not spec:
            raise ValueError("插件规格未注册")
        run_context = self._normalize_execution_context(execution_context)

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
            return self._build_run_response(saved, plugin, run_context)

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
            return self._build_run_response(saved, plugin, run_context)

        if run_context.mode == "remote" and not self.REMOTE_EXECUTION_ENABLED:
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.REJECTED,
                operator=operator,
                approval_ticket=approval_ticket,
                error_code="EXECUTOR_REMOTE_DISABLED",
                error_message="远程执行未启用，当前仅支持本地执行",
                task_id=task_id,
            )
            saved = self.audit_repository.save(audit)
            return self._build_run_response(saved, plugin, run_context)

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
            return self._build_run_response(saved, plugin, run_context)

        timeout_value = max(1, min(timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS, 120))
        started = time.perf_counter()

        try:
            if run_context.mode == "remote":
                result = self._execute_remote_command(run_context, tokens, timeout_value)
            else:
                result = self._execute_local_command(tokens, timeout_value)
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
                return self._build_run_response(saved, plugin, run_context)

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
            return self._build_run_response(saved, plugin, run_context)
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
            return self._build_run_response(saved, plugin, run_context)
        except NotImplementedError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            audit = self._build_audit(
                plugin_key=plugin_key,
                command=command,
                readonly=readonly,
                status=ExecutorRunStatus.REJECTED,
                operator=operator,
                approval_ticket=approval_ticket,
                duration_ms=duration_ms,
                task_id=task_id,
                error_code="EXECUTOR_REMOTE_NOT_IMPLEMENTED",
                error_message=str(exc),
            )
            saved = self.audit_repository.save(audit)
            plugin = self._apply_failure_state(plugin, str(exc))
            return self._build_run_response(saved, plugin, run_context)
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
            return self._build_run_response(saved, plugin, run_context)
