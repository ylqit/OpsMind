"""建议接口。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.llm.structured_output import run_guarded_scenario_chat
from engine.runtime.models import ArtifactRef, Claim, EvidenceLocator, EvidenceRef, RecommendationFeedback, TaskStatus, TaskType

from .deps import (
    get_ai_writeback_repository_dep,
    get_incident_service,
    get_llm_router_dep,
    get_recommendation_feedback_repository_dep,
    get_recommendation_service,
    get_task_manager,
    get_traffic_engine,
    resolve_access_logs,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationGenerateRequest(BaseModel):
    """建议生成请求。"""

    incident_id: str = Field(..., description="异常 ID")
    kinds: list[str] = Field(default_factory=list, description="建议类型")


class RecommendationAIReviewRequest(BaseModel):
    """AI 复核请求。"""

    provider: str | None = Field(default=None, description="指定 Provider")


class RecommendationReviewSchema(BaseModel):
    """AI 复核结构。"""

    summary: str = Field(..., min_length=1, max_length=800)
    risk_level: str = Field(..., pattern="^(high|medium|low)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_assessment: str = Field(..., min_length=1, max_length=500)
    rollback_plan: list[str] = Field(default_factory=list, max_length=8)
    validation_checks: list[str] = Field(default_factory=list, max_length=8)
    evidence_citations: list[str] = Field(default_factory=list, max_length=8)
    role_views: dict[str, dict[str, Any]] | None = None


class RecommendationAIReviewPayload(BaseModel):
    """结构化 AI 复核响应。"""

    recommendation_id: str
    incident_id: str
    provider: str
    summary: str
    risk_level: str = "medium"
    confidence: float = 0.5
    risk_assessment: str = ""
    rollback_plan: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    evidence_citations: list[str] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    role_views: dict[str, dict[str, Any]] = Field(default_factory=dict)
    parse_mode: str = "fallback"
    validation_status: str = "fallback_template"
    retry_count: int = 0
    guardrail_error_code: str = ""
    guardrail_error_message: str = ""


class RecommendationFeedbackRequest(BaseModel):
    """建议反馈请求。"""

    action: str = Field(..., pattern="^(adopt|reject|rewrite)$")
    reason_code: str = Field(default="", max_length=120)
    comment: str = Field(default="", max_length=1000)
    operator: str = Field(default="anonymous", max_length=80)
    task_id: str | None = Field(default=None, max_length=80)


class RecommendationFeedbackListResponse(BaseModel):
    """建议反馈列表响应。"""

    recommendation_id: str
    summary: dict[str, int]
    items: list[dict[str, Any]]


def _artifact_filename(artifact: dict[str, Any]) -> str:
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        return str(artifact.get("artifact_id") or "artifact")
    return Path(raw_path).name or raw_path


def _normalize_evidence_confidence(priority: int, signal_strength: str) -> float:
    if signal_strength == "high":
        return 0.9 if priority >= 85 else 0.82
    if signal_strength == "medium":
        return 0.68 if priority >= 70 else 0.58
    return 0.4


def _build_evidence_ref(payload: dict[str, Any]) -> dict[str, Any]:
    """统一建议详情里的证据结构，兼容现有页面字段并补齐公共 EvidenceRef。"""

    locator_payload = dict(payload.get("locator") or payload.get("source_ref") or {})
    artifact_ref = payload.get("artifact_ref") if isinstance(payload.get("artifact_ref"), dict) else None
    artifact_id = str(payload.get("artifact_id") or locator_payload.get("artifact_id") or "").strip()
    if artifact_ref:
        if not artifact_id:
            artifact_id = str(artifact_ref.get("artifact_id") or "").strip()
        if artifact_ref.get("task_id") and not locator_payload.get("task_id"):
            locator_payload["task_id"] = artifact_ref.get("task_id")
        if artifact_ref.get("artifact_id") and not locator_payload.get("artifact_id"):
            locator_payload["artifact_id"] = artifact_ref.get("artifact_id")
    jump = payload.get("jump") if isinstance(payload.get("jump"), dict) else {}
    if jump.get("kind") and not locator_payload.get("jump_kind"):
        locator_payload["jump_kind"] = str(jump.get("kind"))

    priority = int(payload.get("priority") or 50)
    signal_strength = str(payload.get("signal_strength") or "medium")
    snippet = str(payload.get("snippet") or payload.get("quote") or payload.get("summary") or "").strip()
    evidence = EvidenceRef.model_validate(
        {
            **payload,
            "kind": str(payload.get("kind") or payload.get("source_type") or "other"),
            "source": str(payload.get("source") or payload.get("source_type") or "other"),
            "locator": EvidenceLocator(**locator_payload),
            "artifact_id": artifact_id or None,
            "snippet": snippet[:240],
            "confidence": payload.get("confidence") or _normalize_evidence_confidence(priority, signal_strength),
            "source_ref": locator_payload,
        }
    )
    return evidence.model_dump(mode="python")


def _build_incident_metric_evidence(incident) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if not incident:
        return refs

    for index, item in enumerate(incident.evidence_refs[:8]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("metric") or item.get("type") or f"evidence_{index + 1}")
        summary = str(item.get("summary") or incident.summary or "").strip()
        metric = str(item.get("metric") or "").strip()
        value = item.get("value")
        unit = str(item.get("unit") or "").strip()
        value_text = ""
        if value is not None and str(value).strip():
            value_text = f"{value}{unit}" if unit else str(value)

        refs.append(
            _build_evidence_ref(
                {
                    "evidence_id": f"metric_{incident.incident_id}_{index}",
                    "kind": "metric",
                    "source": "incident",
                    "source_type": "metric_snapshot",
                    "title": title,
                    "summary": summary or "指标快照证据",
                    "quote": value_text,
                    "metric": metric,
                    "priority": int(item.get("priority") or 60),
                    "signal_strength": str(item.get("signal_strength") or "medium"),
                    "artifact_ref": None,
                    "jump": {"kind": "none"},
                    "locator": {
                        "service_key": str(getattr(incident, "service_key", "") or ""),
                        "timestamp": str(item.get("source_ref", {}).get("timestamp") or item.get("timestamp") or ""),
                        "path": str(item.get("source_ref", {}).get("path") or ""),
                        "layer": str(item.get("layer") or "other"),
                    },
                }
            )
        )
    return refs


def _is_safe_artifact_path(path: Path, task_id: str) -> bool:
    """仅允许读取任务目录下的产物文件。"""
    if not task_id.strip():
        return False
    try:
        resolved = path.resolve()
    except Exception:  # noqa: BLE001
        return False
    lowered_parts = [part.lower() for part in resolved.parts]
    return "tasks" in lowered_parts and task_id.lower() in lowered_parts


def _read_artifact_excerpt(path: Path, max_lines: int = 12, max_chars: int = 420) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""
    lines = [line.rstrip() for line in content.splitlines()[:max_lines]]
    joined = "\n".join(lines).strip()
    if len(joined) > max_chars:
        return f"{joined[:max_chars]}..."
    return joined


def _extract_metric_quotes_from_text(text: str) -> list[tuple[str, str]]:
    if not text.strip():
        return []
    patterns = [
        ("error_rate", r"(?:error[_ ]?rate|错误率)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("latency", r"(?:latency|延迟|request_time|avg_latency)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("cpu", r"(?:cpu|CPU)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("memory", r"(?:memory|内存)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("restarts", r"(?:restart|重启)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
    ]
    found: list[tuple[str, str]] = []
    for metric, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        found.append((metric, match.group(1)))
        if len(found) >= 4:
            break
    return found


def _read_artifact_json_payload(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return {}
    try:
        payload = json.loads(content)
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_executor_artifact_evidence(artifact: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    task_id = str(artifact.get("task_id") or "")
    artifact_id = str(artifact.get("artifact_id") or "")
    raw_path = str(artifact.get("path") or "").strip()
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    evidence_items = payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else []

    refs: list[dict[str, Any]] = []
    for index, item in enumerate(evidence_items):
        if not isinstance(item, dict):
            continue
        locator = dict(item.get("locator") or item.get("source_ref") or {})
        locator.setdefault("task_id", task_id)
        locator.setdefault("artifact_id", artifact_id)
        locator.setdefault("path", raw_path)
        locator.setdefault("layer", "task")
        if execution.get("execution_id") and not locator.get("execution_id"):
            locator["execution_id"] = execution.get("execution_id")
        if execution.get("status") and not locator.get("status"):
            locator["status"] = execution.get("status")
        refs.append(
            _build_evidence_ref(
                {
                    **item,
                    "artifact_ref": artifact,
                    "jump": {
                        "kind": "artifact",
                        "task_id": task_id,
                        "artifact_id": artifact_id,
                    },
                    "locator": locator,
                    "priority": int(item.get("priority") or 86),
                    "signal_strength": str(item.get("signal_strength") or "high"),
                    "source_type": str(item.get("source_type") or "executor_result"),
                }
            )
        )

    if refs:
        return refs

    execution_id = str(execution.get("execution_id") or "")
    status = str(execution.get("status") or "")
    plugin_key = str(execution.get("plugin_key") or "")
    command = str(execution.get("command") or "")
    quote = str(execution.get("stderr_preview") or execution.get("stdout_preview") or "").strip()[:600]
    return [
        _build_evidence_ref(
            {
                "evidence_id": f"executor_{execution_id or artifact_id}",
                "kind": "executor",
                "source": "executor_plugin",
                "source_type": "executor_result",
                "title": f"{plugin_key or '执行插件'} 执行结果",
                "summary": f"命令状态 {status or '-'}，命令：{command or '-'}",
                "quote": quote,
                "priority": 86,
                "signal_strength": "high",
                "artifact_ref": artifact,
                "jump": {
                    "kind": "artifact",
                    "task_id": task_id,
                    "artifact_id": artifact_id,
                },
                "locator": {
                    "task_id": task_id,
                    "artifact_id": artifact_id,
                    "path": raw_path,
                    "execution_id": execution_id,
                    "status": status,
                    "source": plugin_key,
                    "layer": "task",
                },
            }
        )
    ]


def _build_artifact_evidence(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_id = str(artifact.get("artifact_id") or "")
    task_id = str(artifact.get("task_id") or "")
    kind = str(artifact.get("kind") or "")
    preview = str(artifact.get("preview") or "").strip()
    raw_path = str(artifact.get("path") or "").strip()
    filename = _artifact_filename(artifact)

    refs: list[dict[str, Any]] = [
        _build_evidence_ref(
            {
                "evidence_id": f"artifact_{artifact_id or filename}",
                "kind": "artifact",
                "source": "artifact",
                "source_type": "artifact",
                "title": filename,
                "summary": preview or f"任务产物（{kind or 'artifact'}）",
                "quote": preview[:200],
                "metric": "",
                "priority": 78,
                "signal_strength": "high" if kind in {"manifest", "diff", "json"} else "medium",
                "artifact_ref": artifact,
                "jump": {
                    "kind": "artifact",
                    "task_id": task_id,
                    "artifact_id": artifact_id,
                },
                "locator": {
                    "task_id": task_id,
                    "artifact_id": artifact_id,
                    "path": raw_path,
                    "layer": "artifact",
                },
            }
        )
    ]

    if not raw_path:
        return refs
    artifact_path = Path(raw_path)
    if not artifact_path.exists() or not artifact_path.is_file():
        return refs
    if not _is_safe_artifact_path(artifact_path, task_id=task_id):
        return refs

    excerpt = _read_artifact_excerpt(artifact_path)
    if kind == "json" or artifact_path.suffix.lower() == ".json":
        payload = _read_artifact_json_payload(artifact_path)
        if str(payload.get("source") or "").strip() == "executor_plugin":
            refs.extend(_build_executor_artifact_evidence(artifact, payload))
    if excerpt:
        if kind in {"log_snippet", "text"} or artifact_path.suffix.lower() == ".log" or "access" in filename.lower():
            refs.append(
                _build_evidence_ref(
                    {
                        "evidence_id": f"log_{artifact_id or filename}",
                        "kind": "log",
                        "source": "artifact",
                        "source_type": "log_snippet",
                        "title": f"{filename} 日志片段",
                        "summary": "来自任务产物的现场日志样本",
                        "quote": excerpt,
                        "metric": "",
                        "priority": 84,
                        "signal_strength": "high",
                        "artifact_ref": artifact,
                        "jump": {
                            "kind": "artifact",
                            "task_id": task_id,
                            "artifact_id": artifact_id,
                        },
                        "locator": {
                            "task_id": task_id,
                            "artifact_id": artifact_id,
                            "path": raw_path,
                            "layer": "artifact",
                        },
                    }
                )
            )

        for metric, value in _extract_metric_quotes_from_text(excerpt):
            refs.append(
                _build_evidence_ref(
                    {
                        "evidence_id": f"metric_{artifact_id or filename}_{metric}",
                        "kind": "metric",
                        "source": "artifact",
                        "source_type": "metric_snapshot",
                        "title": f"{filename} 指标快照",
                        "summary": f"从产物中提取到 {metric}={value}",
                        "quote": f"{metric}={value}",
                        "metric": metric,
                        "priority": 82,
                        "signal_strength": "medium",
                        "artifact_ref": artifact,
                        "jump": {
                            "kind": "artifact",
                            "task_id": task_id,
                            "artifact_id": artifact_id,
                        },
                        "locator": {
                            "task_id": task_id,
                            "artifact_id": artifact_id,
                            "path": raw_path,
                            "layer": "artifact",
                        },
                    }
                )
            )
    return refs


def _build_log_sample_evidence(log_samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(log_samples[:4]):
        status = int(item.get("status") or 0)
        latency_ms = float(item.get("latency_ms") or 0.0)
        refs.append(
            _build_evidence_ref(
                {
                    "evidence_id": f"log_sample_{index}",
                    "kind": "log",
                    "source": "traffic",
                    "source_type": "log_snippet",
                    "title": f"{item.get('path') or '/'} 访问日志样本",
                    "summary": f"状态码 {status}，耗时 {round(latency_ms, 2)} ms，来源 {item.get('client_ip') or '-'}",
                    "quote": str(item.get("user_agent") or "").strip(),
                    "metric": "status" if status >= 500 else "latency_ms",
                    "priority": 90 if status >= 500 else 76,
                    "signal_strength": "high" if status >= 500 else "medium",
                    "artifact_ref": None,
                    "jump": {"kind": "none"},
                    "locator": {
                        "service_key": str(item.get("service_key") or ""),
                        "timestamp": str(item.get("timestamp") or ""),
                        "path": str(item.get("path") or ""),
                        "status": status,
                        "client_ip": str(item.get("client_ip") or ""),
                        "geo_label": str(item.get("geo_label") or ""),
                        "layer": "traffic",
                    },
                }
            )
        )
    return refs


def _deduplicate_evidence(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in refs:
        artifact_ref = item.get("artifact_ref") or {}
        artifact_id = str(artifact_ref.get("artifact_id") or "")
        key = (
            str(item.get("source_type") or ""),
            str(item.get("title") or ""),
            str(item.get("quote") or "")[:120],
            artifact_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return sorted(deduplicated, key=lambda item: int(item.get("priority") or 0), reverse=True)


def _build_evidence_summary(refs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(refs),
        "artifact": len([item for item in refs if item.get("source_type") == "artifact"]),
        "log_snippet": len([item for item in refs if item.get("source_type") == "log_snippet"]),
        "metric_snapshot": len([item for item in refs if item.get("source_type") == "metric_snapshot"]),
        "incident_evidence": len([item for item in refs if item.get("source_type") == "incident_evidence"]),
        "executor_result": len([item for item in refs if item.get("source_type") == "executor_result"]),
    }


def _collect_evidence_ids(refs: list[dict[str, Any]], limit: int = 3) -> list[str]:
    evidence_ids: list[str] = []
    for item in refs:
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id or evidence_id in evidence_ids:
            continue
        evidence_ids.append(evidence_id)
        if len(evidence_ids) >= limit:
            break
    return evidence_ids


def _build_claim(
    *,
    claim_id: str,
    kind: str,
    statement: str,
    evidence_ids: list[str],
    confidence: float,
    limitations: list[str],
    title: str = "",
    source: str = "recommendation",
    next_step: str | None = None,
) -> dict[str, Any] | None:
    normalized_statement = str(statement).strip()
    if not normalized_statement:
        return None
    claim = Claim.model_validate(
        {
            "claim_id": claim_id,
            "kind": kind,
            "statement": normalized_statement,
            "evidence_ids": [item for item in evidence_ids if item],
            "confidence": confidence,
            "limitations": [item for item in limitations if str(item).strip()],
            "title": title,
            "source": source,
            "next_step": str(next_step).strip() or None if next_step is not None else None,
        }
    )
    return claim.model_dump(mode="python")


def _build_recommendation_limitations(
    *,
    evidence_status: str,
    evidence_summary: dict[str, int],
    risk_note: str,
) -> list[str]:
    limitations: list[str] = []
    if evidence_status != "sufficient":
        limitations.append("当前可追溯证据不足，建议先补充日志、指标或任务产物。")
    if int(evidence_summary.get("artifact", 0)) == 0:
        limitations.append("缺少任务产物支撑，配置草稿仍需人工复核。")
    if int(evidence_summary.get("log_snippet", 0)) == 0:
        limitations.append("缺少现场日志样本，异常触发路径仍需补充确认。")
    if risk_note.strip():
        limitations.append("请结合风险提示与回滚预案评估执行窗口。")

    deduplicated: list[str] = []
    for item in limitations:
        if item not in deduplicated:
            deduplicated.append(item)
    return deduplicated[:3]


def _build_insufficient_evidence_ref(recommendation, incident) -> dict[str, Any]:
    incident_summary = str(getattr(incident, "summary", "") or "").strip()
    recommendation_summary = str(getattr(recommendation, "recommendation", "") or "").strip()
    return _build_evidence_ref(
        {
            "evidence_id": f"incident_context_{recommendation.recommendation_id}",
            "kind": "analysis",
            "source": "incident",
            "source_type": "incident_evidence",
            "title": "证据不足说明",
            "summary": incident_summary or "当前建议缺少可追溯的现场证据，仅保留 incident 上下文作为提示。",
            "quote": recommendation_summary or "建议暂不具备执行条件",
            "metric": "",
            "priority": 95,
            "signal_strength": "low",
            "artifact_ref": None,
            "jump": {"kind": "none"},
            "locator": {
                "service_key": str(getattr(incident, "service_key", "") or ""),
                "layer": "diagnosis",
            },
        }
    )


def _build_recommendation_evidence_payload(recommendation, incident, log_samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    refs.extend(_build_incident_metric_evidence(incident))
    refs.extend(_build_log_sample_evidence(log_samples or []))
    for artifact in recommendation.artifact_refs:
        if isinstance(artifact, dict):
            refs.extend(_build_artifact_evidence(artifact))

    evidence_refs = _deduplicate_evidence(refs)
    actionable_count = len(
        [item for item in evidence_refs if str(item.get("source_type") or "") in {"artifact", "log_snippet", "metric_snapshot"}]
    )
    insufficient = actionable_count == 0

    if insufficient:
        fallback_refs = [_build_insufficient_evidence_ref(recommendation, incident)]
        return {
            "evidence_refs": fallback_refs,
            "evidence_status": "insufficient",
            "evidence_message": "证据不足：当前缺少可追溯的任务产物、日志片段或指标快照，暂不建议执行强变更。",
            "confidence_effective": min(float(recommendation.confidence), 0.35),
            "recommendation_effective": "证据不足：建议先补充日志与指标证据，再进行变更决策。",
            "evidence_summary": _build_evidence_summary(fallback_refs),
        }

    return {
        "evidence_refs": evidence_refs,
        "evidence_status": "sufficient",
        "evidence_message": "已提取现场证据，可追溯到任务产物与指标快照。",
        "confidence_effective": float(recommendation.confidence),
        "recommendation_effective": recommendation.recommendation,
        "evidence_summary": _build_evidence_summary(evidence_refs),
    }


def _build_recommendation_claims(recommendation, incident, evidence_payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_refs = [item for item in evidence_payload.get("evidence_refs") or [] if isinstance(item, dict)]
    evidence_ids = _collect_evidence_ids(evidence_refs, limit=3)
    confidence = float(evidence_payload.get("confidence_effective") or recommendation.confidence or 0.5)
    limitations = _build_recommendation_limitations(
        evidence_status=str(evidence_payload.get("evidence_status") or "insufficient"),
        evidence_summary=evidence_payload.get("evidence_summary") or {},
        risk_note=str(getattr(recommendation, "risk_note", "") or ""),
    )
    claims: list[dict[str, Any]] = []

    summary_claim = _build_claim(
        claim_id=f"{recommendation.recommendation_id}_summary",
        kind="summary",
        title="建议结论",
        statement=str(evidence_payload.get("recommendation_effective") or recommendation.recommendation or ""),
        evidence_ids=evidence_ids,
        confidence=confidence,
        limitations=limitations,
        source="recommendation_detail",
    )
    if summary_claim:
        claims.append(summary_claim)

    observation_text = str(getattr(recommendation, "observation", "") or getattr(incident, "summary", "") or "").strip()
    observation_claim = _build_claim(
        claim_id=f"{recommendation.recommendation_id}_observation",
        kind="cause",
        title="触发观察",
        statement=observation_text,
        evidence_ids=evidence_ids[:2] or evidence_ids,
        confidence=max(0.3, min(confidence, 0.78)),
        limitations=limitations,
        source="recommendation_detail",
    )
    if observation_claim:
        claims.append(observation_claim)

    risk_text = str(getattr(recommendation, "risk_note", "") or "").strip()
    risk_claim = _build_claim(
        claim_id=f"{recommendation.recommendation_id}_risk",
        kind="risk",
        title="风险提示",
        statement=risk_text or "建议执行前需要人工确认变更风险和回滚策略。",
        evidence_ids=evidence_ids[:2] or evidence_ids,
        confidence=max(0.28, min(confidence, 0.7)),
        limitations=limitations,
        source="recommendation_detail",
    )
    if risk_claim:
        claims.append(risk_claim)

    return claims


def _build_recommendation_ai_claims(
    recommendation,
    review_payload: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    confidence = float(review_payload.get("confidence") or 0.5)
    evidence_ids = _collect_evidence_ids(evidence_refs, limit=3)
    limitations = _build_recommendation_limitations(
        evidence_status="sufficient" if evidence_ids else "insufficient",
        evidence_summary={
            "artifact": len([item for item in evidence_refs if item.get("source_type") == "artifact"]),
            "log_snippet": len([item for item in evidence_refs if item.get("source_type") == "log_snippet"]),
        },
        risk_note=str(review_payload.get("risk_assessment") or ""),
    )
    claims: list[dict[str, Any]] = []

    summary_claim = _build_claim(
        claim_id=f"{recommendation.recommendation_id}_ai_summary",
        kind="summary",
        title="AI 复核结论",
        statement=str(review_payload.get("summary") or ""),
        evidence_ids=evidence_ids,
        confidence=confidence,
        limitations=limitations,
        source="recommendation_ai_review",
    )
    if summary_claim:
        claims.append(summary_claim)

    risk_claim = _build_claim(
        claim_id=f"{recommendation.recommendation_id}_ai_risk",
        kind="risk",
        title="AI 风险判断",
        statement=str(review_payload.get("risk_assessment") or ""),
        evidence_ids=evidence_ids[:2] or evidence_ids,
        confidence=max(0.3, min(confidence, 0.76)),
        limitations=limitations,
        source="recommendation_ai_review",
    )
    if risk_claim:
        claims.append(risk_claim)

    checks = [item for item in review_payload.get("validation_checks") or [] if str(item).strip()]
    if checks:
        action_claim = _build_claim(
            claim_id=f"{recommendation.recommendation_id}_ai_checks",
            kind="action",
            title="验证动作",
            statement="；".join(checks[:3]),
            evidence_ids=evidence_ids[:2] or evidence_ids,
            confidence=max(0.28, min(confidence, 0.72)),
            limitations=["复核建议仍需结合变更窗口和回滚方案完成最终确认。"],
            source="recommendation_ai_review",
        )
        if action_claim:
            claims.append(action_claim)

    return claims


def _build_artifact_group(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    group: dict[str, dict[str, Any] | None] = {
        "baseline": None,
        "recommended": None,
        "diff": None,
        "metadata": None,
    }
    for artifact in artifacts:
        filename = _artifact_filename(artifact).lower()
        kind = str(artifact.get("kind") or "").strip().lower()
        if kind == "json" and "-manifest-meta" in filename and not group["metadata"]:
            group["metadata"] = artifact
            continue
        if kind == "diff" and not group["diff"]:
            group["diff"] = artifact
            continue
        if kind == "manifest" and "-baseline" in filename and not group["baseline"]:
            group["baseline"] = artifact
            continue
        if kind == "manifest" and "-recommended" in filename and not group["recommended"]:
            group["recommended"] = artifact
            continue
        if kind == "manifest" and not group["recommended"]:
            group["recommended"] = artifact
    if not group["baseline"] and group["recommended"]:
        group["baseline"] = group["recommended"]
    return group


def _read_artifact_json(path_value: str) -> dict[str, Any] | None:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _summarize_diff_preview_v2(artifact: dict[str, Any]) -> dict[str, Any]:
    content = str(artifact.get("preview") or "").strip()
    from_filename = ""
    to_filename = ""
    added_lines = 0
    removed_lines = 0
    hunk_count = 0
    for line in content.splitlines():
        if line.startswith("--- "):
            from_filename = line.replace("--- ", "", 1).strip()
            continue
        if line.startswith("+++ "):
            to_filename = line.replace("+++ ", "", 1).strip()
            continue
        if line.startswith("@@"):
            hunk_count += 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added_lines += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            removed_lines += 1
    return {
        "from_filename": from_filename,
        "to_filename": to_filename,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "hunk_count": hunk_count,
    }


def _build_artifact_view_entry_v2(view_key: str, artifact: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    filename = _artifact_filename(artifact)
    entry = {
        "view_key": view_key,
        "label": "基线" if view_key == "baseline" else "建议" if view_key == "recommended" else "Diff",
        "filename": filename,
        "kind": str(artifact.get("kind") or ""),
        "artifact_id": str(artifact.get("artifact_id") or ""),
        "task_id": str(artifact.get("task_id") or ""),
        "summary": str(artifact.get("preview") or "").strip(),
    }

    if view_key in {"baseline", "recommended"}:
        section = metadata.get(view_key) if isinstance(metadata, dict) else None
        if isinstance(section, dict):
            entry.update(
                {
                    "line_count": int(section.get("line_count") or 0),
                    "document_count": int(section.get("document_count") or 0),
                    "sha256": str(section.get("sha256") or ""),
                }
            )
            if entry["line_count"] or entry["document_count"]:
                entry["summary"] = (
                    f"{entry['label']} YAML，文档 {entry['document_count']} 个，"
                    f"行数 {entry['line_count']}"
                )
        return entry

    diff_section = metadata.get("diff") if isinstance(metadata, dict) else None
    if isinstance(diff_section, dict):
        entry.update(
            {
                "from_filename": str((metadata.get("baseline") or {}).get("filename") or ""),
                "to_filename": str((metadata.get("recommended") or {}).get("filename") or ""),
                "added_lines": int(diff_section.get("added_lines") or 0),
                "removed_lines": int(diff_section.get("removed_lines") or 0),
                "hunk_count": int(diff_section.get("hunk_count") or 0),
            }
        )
    else:
        entry.update(_summarize_diff_preview_v2(artifact))
    entry["summary"] = (
        f"差异摘要：新增 {entry.get('added_lines', 0)} 行，"
        f"删除 {entry.get('removed_lines', 0)} 行，"
        f"变更块 {entry.get('hunk_count', 0)} 处"
    )
    return entry


def _build_artifact_views_payload_v2(recommendation) -> dict[str, Any]:
    artifacts = [item for item in recommendation.artifact_refs if isinstance(item, dict)]
    if not artifacts:
        return {
            "primary_view": None,
            "available_views": [],
            "baseline": None,
            "recommended": None,
            "diff": None,
        }

    group = _build_artifact_group(artifacts)
    metadata_artifact = group.get("metadata")
    metadata = (
        _read_artifact_json(str(metadata_artifact.get("path") or ""))
        if isinstance(metadata_artifact, dict)
        else None
    )

    baseline_entry = (
        _build_artifact_view_entry_v2("baseline", group["baseline"], metadata)
        if isinstance(group.get("baseline"), dict)
        else None
    )
    recommended_entry = (
        _build_artifact_view_entry_v2("recommended", group["recommended"], metadata)
        if isinstance(group.get("recommended"), dict)
        else None
    )
    diff_entry = (
        _build_artifact_view_entry_v2("diff", group["diff"], metadata)
        if isinstance(group.get("diff"), dict)
        else None
    )

    available_views = [
        key
        for key, entry in (
            ("baseline", baseline_entry),
            ("recommended", recommended_entry),
            ("diff", diff_entry),
        )
        if entry
    ]
    primary_view = "recommended" if recommended_entry else "diff" if diff_entry else "baseline" if baseline_entry else None
    return {
        "primary_view": primary_view,
        "available_views": available_views,
        "baseline": baseline_entry,
        "recommended": recommended_entry,
        "diff": diff_entry,
    }


def _summarize_diff_preview(artifact: dict[str, Any]) -> dict[str, Any]:
    content = str(artifact.get("preview") or "").strip()
    from_filename = ""
    to_filename = ""
    added_lines = 0
    removed_lines = 0
    hunk_count = 0
    for line in content.splitlines():
        if line.startswith("--- "):
            from_filename = line.replace("--- ", "", 1).strip()
            continue
        if line.startswith("+++ "):
            to_filename = line.replace("+++ ", "", 1).strip()
            continue
        if line.startswith("@@"):
            hunk_count += 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added_lines += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            removed_lines += 1
    return {
        "from_filename": from_filename,
        "to_filename": to_filename,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "hunk_count": hunk_count,
    }


def _normalize_resource_types(value: Any) -> list[dict[str, Any]]:
    """标准化资源对象列表，避免前端处理异常结构。"""
    if not isinstance(value, list):
        return []
    resource_types: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if not kind:
            continue
        try:
            count = max(0, int(item.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        resource_types.append({"kind": kind, "count": count})
    return resource_types


def _infer_change_level(total_changed_lines: int, hunk_count: int) -> str:
    if total_changed_lines >= 30 or hunk_count >= 6:
        return "high"
    if total_changed_lines >= 10 or hunk_count >= 3:
        return "medium"
    return "low"


def _normalize_risk_summary(value: Any) -> dict[str, Any] | None:
    """统一风险摘要结构，确保字段稳定。"""
    if not isinstance(value, dict):
        return None
    level = str(value.get("level") or "").strip().lower()
    if level not in {"high", "medium", "low"}:
        level = "medium"
    highlights = (
        [str(item).strip() for item in value.get("highlights", []) if str(item).strip()]
        if isinstance(value.get("highlights"), list)
        else []
    )
    try:
        score = max(0, int(value.get("score") or 0))
    except (TypeError, ValueError):
        score = 0
    return {
        "level": level,
        "score": score,
        "review_required": bool(value.get("review_required", True)),
        "highlights": highlights[:6],
    }


def _normalize_resource_hints(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    added_types = (
        [str(item).strip() for item in value.get("added_types", []) if str(item).strip()]
        if isinstance(value.get("added_types"), list)
        else []
    )
    removed_types = (
        [str(item).strip() for item in value.get("removed_types", []) if str(item).strip()]
        if isinstance(value.get("removed_types"), list)
        else []
    )
    return {
        "baseline_types": _normalize_resource_types(value.get("baseline_types")),
        "recommended_types": _normalize_resource_types(value.get("recommended_types")),
        "added_types": added_types,
        "removed_types": removed_types,
    }


def _build_artifact_view_entry(view_key: str, artifact: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    filename = _artifact_filename(artifact)
    entry = {
        "view_key": view_key,
        "label": "基线" if view_key == "baseline" else "建议" if view_key == "recommended" else "Diff",
        "filename": filename,
        "kind": str(artifact.get("kind") or ""),
        "artifact_id": str(artifact.get("artifact_id") or ""),
        "task_id": str(artifact.get("task_id") or ""),
        "summary": str(artifact.get("preview") or "").strip(),
    }

    if view_key in {"baseline", "recommended"}:
        section = metadata.get(view_key) if isinstance(metadata, dict) else None
        if isinstance(section, dict):
            resource_types = _normalize_resource_types(section.get("resource_types"))
            entry.update(
                {
                    "line_count": int(section.get("line_count") or 0),
                    "document_count": int(section.get("document_count") or 0),
                    "sha256": str(section.get("sha256") or ""),
                    "resource_types": resource_types,
                }
            )
            if entry["line_count"] or entry["document_count"]:
                entry["summary"] = (
                    f"{entry['label']} YAML，文档 {entry['document_count']} 个，"
                    f"行数 {entry['line_count']}"
                )
            if resource_types:
                resource_summary = "、".join(f"{item['kind']} x{item['count']}" for item in resource_types[:4])
                entry["summary"] = f"{entry['summary']}，对象 {resource_summary}"
        return entry

    diff_section = metadata.get("diff") if isinstance(metadata, dict) else None
    if isinstance(diff_section, dict):
        added_lines = int(diff_section.get("added_lines") or 0)
        removed_lines = int(diff_section.get("removed_lines") or 0)
        hunk_count = int(diff_section.get("hunk_count") or 0)
        total_changed_lines = int(diff_section.get("total_changed_lines") or (added_lines + removed_lines))
        entry.update(
            {
                "from_filename": str((metadata.get("baseline") or {}).get("filename") or ""),
                "to_filename": str((metadata.get("recommended") or {}).get("filename") or ""),
                "added_lines": added_lines,
                "removed_lines": removed_lines,
                "hunk_count": hunk_count,
                "total_changed_lines": total_changed_lines,
                "change_level": str(diff_section.get("change_level") or _infer_change_level(total_changed_lines, hunk_count)),
            }
        )
    else:
        entry.update(_summarize_diff_preview(artifact))
        total_changed_lines = int(entry.get("added_lines") or 0) + int(entry.get("removed_lines") or 0)
        entry["total_changed_lines"] = total_changed_lines
        entry["change_level"] = _infer_change_level(total_changed_lines, int(entry.get("hunk_count") or 0))
    entry["summary"] = (
        f"差异摘要：新增 {entry.get('added_lines', 0)} 行，"
        f"删除 {entry.get('removed_lines', 0)} 行，"
        f"变更块 {entry.get('hunk_count', 0)} 处，"
        f"强度 {entry.get('change_level', 'low')}"
    )
    return entry


def _build_artifact_views_payload(recommendation) -> dict[str, Any]:
    """构建三视图载荷，同时补充风险与变更评审信息。"""
    artifacts = [item for item in recommendation.artifact_refs if isinstance(item, dict)]
    if not artifacts:
        return {
            "primary_view": None,
            "available_views": [],
            "baseline": None,
            "recommended": None,
            "diff": None,
            "risk_summary": None,
            "resource_hints": None,
            "change_stats": None,
        }

    group = _build_artifact_group(artifacts)
    metadata_artifact = group.get("metadata")
    metadata = (
        _read_artifact_json(str(metadata_artifact.get("path") or ""))
        if isinstance(metadata_artifact, dict)
        else None
    )
    risk_summary = _normalize_risk_summary(metadata.get("risk_summary")) if isinstance(metadata, dict) else None
    resource_hints = _normalize_resource_hints(metadata.get("resource_hints")) if isinstance(metadata, dict) else None

    baseline_entry = (
        _build_artifact_view_entry("baseline", group["baseline"], metadata)
        if isinstance(group.get("baseline"), dict)
        else None
    )
    recommended_entry = (
        _build_artifact_view_entry("recommended", group["recommended"], metadata)
        if isinstance(group.get("recommended"), dict)
        else None
    )
    diff_entry = (
        _build_artifact_view_entry("diff", group["diff"], metadata)
        if isinstance(group.get("diff"), dict)
        else None
    )

    if baseline_entry and not baseline_entry.get("resource_types") and resource_hints:
        baseline_entry["resource_types"] = resource_hints.get("baseline_types") or []
    if recommended_entry and not recommended_entry.get("resource_types") and resource_hints:
        recommended_entry["resource_types"] = resource_hints.get("recommended_types") or []
    if diff_entry and risk_summary:
        diff_entry["risk_level"] = risk_summary.get("level")

    available_views = [
        key
        for key, entry in (
            ("baseline", baseline_entry),
            ("recommended", recommended_entry),
            ("diff", diff_entry),
        )
        if entry
    ]
    primary_view = "recommended" if recommended_entry else "diff" if diff_entry else "baseline" if baseline_entry else None
    change_stats = (
        {
            "total_changed_lines": int((diff_entry or {}).get("total_changed_lines") or 0),
            "change_level": str((diff_entry or {}).get("change_level") or "low"),
            "added_lines": int((diff_entry or {}).get("added_lines") or 0),
            "removed_lines": int((diff_entry or {}).get("removed_lines") or 0),
            "hunk_count": int((diff_entry or {}).get("hunk_count") or 0),
        }
        if diff_entry
        else None
    )
    return {
        "primary_view": primary_view,
        "available_views": available_views,
        "baseline": baseline_entry,
        "recommended": recommended_entry,
        "diff": diff_entry,
        "risk_summary": risk_summary,
        "resource_hints": resource_hints,
        "change_stats": change_stats,
    }


def _to_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _normalize_risk_level(value: Any) -> str:
    level = str(value or "").strip().lower()
    if level in {"high", "medium", "low"}:
        return level
    return "medium"


def _normalize_confidence(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def _build_fallback_review_role_views(
    recommendation,
    incident,
    validation_checks: list[str],
    rollback_plan: list[str],
) -> dict[str, dict[str, Any]]:
    incident_tags = [str(tag).replace("_", " ").strip() for tag in (incident.reasoning_tags or []) if str(tag).strip()]
    if not incident_tags:
        incident_tags = ["当前异常标签有限，需补充上下文"]

    traffic_findings = [item for item in incident_tags if any(keyword in item for keyword in ["traffic", "流量", "错误率", "延迟"])]
    if not traffic_findings:
        traffic_findings = incident_tags[:2]

    resource_findings = [item for item in incident_tags if any(keyword in item for keyword in ["resource", "cpu", "memory", "资源", "重启", "oom"])]
    if not resource_findings:
        resource_findings = incident_tags[:2]

    risk_findings = [recommendation.risk_note.strip()] if str(recommendation.risk_note or "").strip() else []
    if str(incident.severity).lower() == "critical":
        risk_findings.append("异常严重度为 critical，建议先止血后优化")
    if not risk_findings:
        risk_findings = ["建议采用渐进式发布，避免一次性放大全量风险"]

    return {
        "traffic": {
            "headline": "流量视角关注入口稳定性，先验证错误率与延迟是否回落。",
            "key_findings": traffic_findings[:6],
            "actions": validation_checks[:3] or ["先在灰度流量中验证关键指标"],
        },
        "resource": {
            "headline": "资源视角关注容量与限额，避免新配置触发资源抖动。",
            "key_findings": resource_findings[:6],
            "actions": validation_checks[1:4] or validation_checks[:2] or ["核对资源限额并保留回退空间"],
        },
        "risk": {
            "headline": "风险视角建议保留回滚路径，分阶段推进配置变更。",
            "key_findings": risk_findings[:6],
            "actions": rollback_plan[:3] or ["保留旧配置并定义回滚触发条件"],
        },
    }


def _normalize_role_view(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    headline = str(value.get("headline") or "").strip() or str(fallback.get("headline") or "").strip() or "暂无结论"
    key_findings = _to_string_list(value.get("key_findings"), limit=6) or _to_string_list(fallback.get("key_findings"), limit=6)
    actions = _to_string_list(value.get("actions"), limit=6) or _to_string_list(fallback.get("actions"), limit=6)
    return {
        "headline": headline,
        "key_findings": key_findings,
        "actions": actions,
    }


def _normalize_role_views(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_views = payload.get("role_views")
    if not isinstance(raw_views, dict):
        raw_views = {}
    # 统一三视角结构，降低前端分支判断复杂度。
    return {
        "traffic": _normalize_role_view(raw_views.get("traffic"), fallback["traffic"]),
        "resource": _normalize_role_view(raw_views.get("resource"), fallback["resource"]),
        "risk": _normalize_role_view(raw_views.get("risk"), fallback["risk"]),
    }


def _build_fallback_review_payload(recommendation, incident) -> dict[str, Any]:
    risk_level = "high" if incident.severity == "critical" else "medium" if incident.severity == "warning" else "low"
    validation_checks = [
        "在测试或灰度环境先验证建议草稿。",
        "观察错误率、延迟和资源占用是否回落到基线。",
        "确认变更窗口与回滚窗口已经预留。",
    ]
    rollback_plan = [
        "保留当前线上配置快照。",
        "若指标恶化，先回滚到基线草稿并重启相关工作负载。",
        "回滚后复核关键监控项，确认服务恢复。",
    ]
    evidence_citations = [f"tag:{tag}" for tag in incident.reasoning_tags[:3]]
    for artifact in recommendation.artifact_refs[:3]:
        artifact_path = str(artifact.get("path") or artifact.get("artifact_id") or "")
        if artifact_path:
            evidence_citations.append(f"artifact:{artifact_path}")
    if not evidence_citations:
        evidence_citations = ["evidence:incident_summary"]

    return {
        "summary": recommendation.recommendation,
        "risk_level": risk_level,
        "confidence": max(0.5, float(recommendation.confidence)),
        "risk_assessment": recommendation.risk_note or "建议草稿需人工审核后再执行。",
        "rollback_plan": rollback_plan,
        "validation_checks": validation_checks,
        "evidence_citations": evidence_citations,
        "role_views": _build_fallback_review_role_views(recommendation, incident, validation_checks, rollback_plan),
    }


def _normalize_review_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(payload.get("summary") or "").strip() or fallback["summary"],
        "risk_level": _normalize_risk_level(payload.get("risk_level")),
        "confidence": _normalize_confidence(payload.get("confidence"), fallback["confidence"]),
        "risk_assessment": str(payload.get("risk_assessment") or "").strip() or fallback["risk_assessment"],
        "rollback_plan": _to_string_list(payload.get("rollback_plan"), limit=8) or fallback["rollback_plan"],
        "validation_checks": _to_string_list(payload.get("validation_checks"), limit=8) or fallback["validation_checks"],
        "evidence_citations": _to_string_list(payload.get("evidence_citations"), limit=8) or fallback["evidence_citations"],
        "role_views": _normalize_role_views(payload, fallback["role_views"]),
    }


def _resolve_feedback_task_id(recommendation, requested_task_id: str | None) -> str | None:
    task_id = (requested_task_id or "").strip()
    if task_id:
        return task_id
    for artifact in recommendation.artifact_refs:
        if not isinstance(artifact, dict):
            continue
        candidate = str(artifact.get("task_id") or "").strip()
        if candidate:
            return candidate
    return None


def _status_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _serialize_feedback_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    return {
        "feedback_id": str(getattr(item, "feedback_id", "")),
        "recommendation_id": str(getattr(item, "recommendation_id", "")),
        "incident_id": str(getattr(item, "incident_id", "")),
        "task_id": str(getattr(item, "task_id", "") or ""),
        "action": str(getattr(item, "action", "")),
        "reason_code": str(getattr(item, "reason_code", "")),
        "comment": str(getattr(item, "comment", "")),
        "operator": str(getattr(item, "operator", "")),
        "created_at": str(getattr(item, "created_at", "")),
    }


def _collect_task_candidates(recommendation, feedback_items: list[dict[str, Any]]) -> list[str]:
    # 先用产物里的 task_id，再补充反馈里的 task_id，保证推荐详情可回溯到任务链路。
    ordered: list[str] = []
    seen: set[str] = set()

    for artifact in recommendation.artifact_refs:
        if not isinstance(artifact, dict):
            continue
        task_id = str(artifact.get("task_id") or "").strip()
        if not task_id or task_id in seen:
            continue
        ordered.append(task_id)
        seen.add(task_id)

    for item in feedback_items:
        task_id = str(item.get("task_id") or "").strip()
        if not task_id or task_id in seen:
            continue
        ordered.append(task_id)
        seen.add(task_id)
    return ordered


def _read_task_trace_preview(task_manager, task_id: str, limit: int = 20) -> list[dict[str, Any]]:
    if not task_manager or not task_id.strip():
        return []
    trace_store = getattr(task_manager, "trace_store", None)
    tasks_base_dir = getattr(trace_store, "tasks_base_dir", None)
    if not tasks_base_dir:
        return []
    trace_file = Path(tasks_base_dir) / task_id / "trace.jsonl"
    if not trace_file.exists() or not trace_file.is_file():
        return []
    try:
        lines = trace_file.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:  # noqa: BLE001
        return []
    preview: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            preview.append(payload)
    return preview


def _build_task_context(task) -> dict[str, Any]:
    approval = task.approval.model_dump(mode="json") if getattr(task, "approval", None) else None
    return {
        "task_id": str(task.task_id),
        "task_type": _status_value(task.task_type),
        "status": _status_value(task.status),
        "current_stage": _status_value(task.current_stage),
        "progress": int(task.progress),
        "progress_message": str(task.progress_message or ""),
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else "",
        "updated_at": task.updated_at.isoformat() if getattr(task, "updated_at", None) else "",
        "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
        "approval": approval,
    }


def _build_task_trace_summary(trace_preview: list[dict[str, Any]]) -> dict[str, Any]:
    if not trace_preview:
        return {"total_steps": 0, "last_step": None}
    last_step = trace_preview[-1]
    observation = last_step.get("observation") if isinstance(last_step, dict) else {}
    if not isinstance(observation, dict):
        observation = {}
    return {
        "total_steps": len(trace_preview),
        "last_step": {
            "step": str(last_step.get("step") or "-"),
            "action": str(last_step.get("action") or "-"),
            "stage": str(last_step.get("stage") or "-"),
            "summary": str(observation.get("summary") or "-"),
            "created_at": str(last_step.get("created_at") or "-"),
        },
    }


@router.get("/{recommendation_id}")
async def get_recommendation_detail(
    recommendation_id: str,
    recommendation_service=Depends(get_recommendation_service),
    incident_service=Depends(get_incident_service),
    traffic_engine=Depends(get_traffic_engine),
    task_manager=Depends(get_task_manager),
    feedback_repository=Depends(get_recommendation_feedback_repository_dep),
    writeback_repository=Depends(get_ai_writeback_repository_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")

    incident = incident_service.get_incident(recommendation.incident_id)
    log_samples: list[dict[str, Any]] = []
    log_paths = resolve_access_logs()
    if incident and log_paths:
        log_samples = traffic_engine.sample_records(
            log_paths,
            service_key=incident.service_key,
            start_time=incident.time_window_start,
            end_time=incident.time_window_end,
            limit=5,
        )
    evidence_payload = _build_recommendation_evidence_payload(recommendation, incident, log_samples=log_samples)
    artifact_views = _build_artifact_views_payload(recommendation)
    feedback_items: list[dict[str, Any]] = []
    feedback_summary = {"adopt": 0, "reject": 0, "rewrite": 0}
    if feedback_repository and hasattr(feedback_repository, "list_by_recommendation"):
        raw_items = feedback_repository.list_by_recommendation(recommendation_id, limit=80)
        feedback_items = [_serialize_feedback_item(item) for item in raw_items]
        if hasattr(feedback_repository, "summarize_by_recommendation"):
            feedback_summary = feedback_repository.summarize_by_recommendation(recommendation_id)

    task_candidates = _collect_task_candidates(recommendation, feedback_items)
    linked_task = None
    if task_manager and hasattr(task_manager, "get_task"):
        for candidate_id in task_candidates:
            task = task_manager.get_task(candidate_id)
            if task:
                linked_task = task
                break

    trace_task_id = str(linked_task.task_id) if linked_task else (task_candidates[0] if task_candidates else "")
    task_trace_preview = _read_task_trace_preview(task_manager, trace_task_id, limit=30)
    task_context = _build_task_context(linked_task) if linked_task else None

    detail = recommendation.model_dump(mode="json")
    detail.update(evidence_payload)
    detail["log_samples"] = log_samples
    detail["artifact_views"] = artifact_views
    detail["feedback_summary"] = feedback_summary
    detail["feedback_items"] = feedback_items
    detail["task_context"] = task_context
    detail["task_trace_preview"] = task_trace_preview
    detail["task_trace_summary"] = _build_task_trace_summary(task_trace_preview)
    detail["claims"] = _build_recommendation_claims(recommendation, incident, evidence_payload)
    detail["assistant_writebacks"] = [
        item.model_dump(mode="json")
        for item in (writeback_repository.list_by_recommendation(recommendation_id) if writeback_repository else [])
    ]
    return detail


@router.get("/{recommendation_id}/feedback")
async def list_recommendation_feedback(
    recommendation_id: str,
    recommendation_service=Depends(get_recommendation_service),
    feedback_repository=Depends(get_recommendation_feedback_repository_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")
    if not feedback_repository:
        raise HTTPException(status_code=500, detail="反馈存储尚未初始化")

    items = feedback_repository.list_by_recommendation(recommendation_id, limit=80)
    summary = feedback_repository.summarize_by_recommendation(recommendation_id)
    payload = RecommendationFeedbackListResponse(
        recommendation_id=recommendation_id,
        summary=summary,
        items=[item.model_dump(mode="json") for item in items],
    )
    return payload.model_dump(mode="json")


@router.post("/{recommendation_id}/feedback")
async def save_recommendation_feedback(
    recommendation_id: str,
    request: RecommendationFeedbackRequest,
    recommendation_service=Depends(get_recommendation_service),
    feedback_repository=Depends(get_recommendation_feedback_repository_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")
    if not feedback_repository:
        raise HTTPException(status_code=500, detail="反馈存储尚未初始化")

    action = request.action.strip().lower()
    reason_code = request.reason_code.strip()
    if action in {"reject", "rewrite"} and not reason_code:
        raise HTTPException(status_code=422, detail="拒绝或改写反馈必须提供 reason_code")

    feedback = RecommendationFeedback(
        recommendation_id=recommendation.recommendation_id,
        incident_id=recommendation.incident_id,
        task_id=_resolve_feedback_task_id(recommendation, request.task_id),
        action=action,
        reason_code=reason_code,
        comment=request.comment.strip(),
        operator=request.operator.strip() or "anonymous",
    )
    saved = feedback_repository.save(feedback)
    summary = feedback_repository.summarize_by_recommendation(recommendation_id)
    return {
        "item": saved.model_dump(mode="json"),
        "summary": summary,
    }


@router.post("/{recommendation_id}/ai-review")
async def review_recommendation_with_ai(
    recommendation_id: str,
    request: RecommendationAIReviewRequest,
    recommendation_service=Depends(get_recommendation_service),
    incident_service=Depends(get_incident_service),
    llm_router=Depends(get_llm_router_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")

    incident = incident_service.get_incident(recommendation.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="建议对应的异常不存在")

    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")

    evidence_lines = []
    for item in incident.evidence_refs[:6]:
        title = str(item.get("title") or item.get("metric") or item.get("type") or "evidence")
        summary = str(item.get("summary") or item.get("reason") or "")
        value = str(item.get("value") or "").strip()
        text = f"- {title}"
        if value:
            text = f"{text} value={value}"
        if summary:
            text = f"{text} ({summary})"
        evidence_lines.append(text)

    artifact_lines = []
    for artifact in recommendation.artifact_refs[:6]:
        kind = str(artifact.get("kind") or "artifact")
        path = str(artifact.get("path") or artifact.get("artifact_id") or "-")
        preview = str(artifact.get("preview") or "")
        line = f"- {kind}: {path}"
        if preview:
            line = f"{line} ({preview})"
        artifact_lines.append(line)

    fallback_payload = _build_fallback_review_payload(recommendation, incident)
    messages = [
        {
            "role": "system",
            "content": (
                "你是资深 SRE 评审助手。"
                "请严格输出 JSON 对象，字段固定为："
                "summary(string), risk_level(high|medium|low), confidence(0-1),"
                "risk_assessment(string), rollback_plan(string[]),"
                "validation_checks(string[]), evidence_citations(string[]),"
                "role_views(object: traffic/resource/risk，每项包含 headline/key_findings/actions)。"
                "不要输出 markdown，不要输出额外字段。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"incident_id: {incident.incident_id}\n"
                f"service_key: {incident.service_key}\n"
                f"severity: {incident.severity}\n"
                f"incident_summary: {incident.summary}\n"
                f"incident_tags: {', '.join(incident.reasoning_tags) or '-'}\n"
                f"recommendation_kind: {recommendation.kind.value}\n"
                f"recommendation_text: {recommendation.recommendation}\n"
                f"risk_note: {recommendation.risk_note}\n"
                f"incident_evidence:\n{chr(10).join(evidence_lines) if evidence_lines else '-'}\n"
                f"artifacts:\n{chr(10).join(artifact_lines) if artifact_lines else '-'}"
            ),
        },
    ]

    guardrail_result = await run_guarded_scenario_chat(
        llm_router=llm_router,
        assistant_role="资深 SRE 评审助手",
        required_fields=(
            "summary(string), risk_level(high|medium|low), confidence(0-1), "
            "risk_assessment(string), rollback_plan(string[]), "
            "validation_checks(string[]), evidence_citations(string[]), "
            "role_views(object: traffic/resource/risk -> headline/key_findings/actions)"
        ),
        context_lines=[str(messages[1].get("content") or "-")],
        schema_model=RecommendationReviewSchema,
        fallback_payload=fallback_payload,
        provider=request.provider,
        temperature=0.1,
        max_tokens=500,
        source="recommendation_center",
        endpoint="recommendation_ai_review",
        max_retries=1,
    )

    normalized = _normalize_review_payload(guardrail_result.data, fallback_payload)
    evidence_payload = _build_recommendation_evidence_payload(recommendation, incident)
    evidence_refs = [item for item in evidence_payload.get("evidence_refs") or [] if isinstance(item, dict)]
    result = RecommendationAIReviewPayload(
        recommendation_id=recommendation.recommendation_id,
        incident_id=recommendation.incident_id,
        provider=request.provider or llm_router.default_client_name,
        parse_mode=guardrail_result.parse_mode,
        validation_status=guardrail_result.validation_status,
        retry_count=guardrail_result.retry_count,
        guardrail_error_code=guardrail_result.error_code,
        guardrail_error_message=guardrail_result.error_message,
        claims=_build_recommendation_ai_claims(recommendation, normalized, evidence_refs),
        **normalized,
    )
    return result.model_dump(mode="json")


@router.post("/generate")
async def generate_recommendations(
    request: RecommendationGenerateRequest,
    task_manager=Depends(get_task_manager),
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
    llm_router=Depends(get_llm_router_dep),
):
    incident = incident_service.get_incident(request.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="异常不存在")

    async def runner(task):
        await task_manager.set_stage(task.task_id, TaskStatus.COLLECTING, 20, "正在读取异常上下文")
        await task_manager.append_trace(
            task.task_id,
            "collect",
            "load_incident",
            TaskStatus.COLLECTING,
            "已加载异常详情",
            {"incident_id": incident.incident_id, "severity": incident.severity},
        )

        await task_manager.set_stage(task.task_id, TaskStatus.ANALYZING, 55, "正在匹配建议类型")
        await task_manager.append_trace(
            task.task_id,
            "analyze",
            "determine_recommendations",
            TaskStatus.ANALYZING,
            "已生成建议候选集合",
            {"reasoning_tags": incident.reasoning_tags},
        )

        await task_manager.set_stage(task.task_id, TaskStatus.GENERATING, 80, "正在生成配置草稿")
        recommendations, guardrail_summary = await recommendation_service.generate_for_incident(
            task.task_id,
            incident,
            allowed_kinds=request.kinds,
            llm_router=llm_router,
            return_guardrail=True,
        )

        await task_manager.append_trace(
            task.task_id,
            "generate",
            "llm_guardrail",
            TaskStatus.GENERATING,
            "已完成建议结构化校验",
            {
                "fallback_count": guardrail_summary.get("fallback_count", 0),
                "retried_count": guardrail_summary.get("retried_count", 0),
                "schema_error_count": guardrail_summary.get("schema_error_count", 0),
            },
        )

        for item in recommendations:
            for artifact in item.artifact_refs:
                artifact_ref = ArtifactRef.model_validate(artifact)
                await task_manager.attach_artifact(task.task_id, artifact_ref)

        result = {
            "incident_id": incident.incident_id,
            "recommendations": [item.model_dump(mode="json") for item in recommendations],
            "guardrail_summary": guardrail_summary,
        }
        if not recommendations:
            await task_manager.append_trace(
                task.task_id,
                "generate",
                "no_actionable_recommendation",
                TaskStatus.GENERATING,
                "未生成可确认建议，任务自动完成",
                {
                    "incident_id": incident.incident_id,
                    "guardrail_summary": guardrail_summary,
                },
            )
            await task_manager.complete_task(task.task_id, result)
            return result

        await task_manager.wait_for_confirm(task.task_id, result)
        return result

    task = await task_manager.create_task(
        task_type=TaskType.RECOMMENDATION_GENERATION,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
