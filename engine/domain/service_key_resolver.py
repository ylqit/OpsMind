"""
service_key 对齐工具。

统一处理 Docker、日志与显式传入 service_key 的归一化、回退与对齐说明。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


def _normalize_segment(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip().strip("/")
    if not text:
        return fallback
    normalized = text.replace("\\", "/").replace(" ", "-").replace("__", "_")
    normalized = normalized.replace("//", "/")
    return normalized.lower()


def _normalize_path_prefix(path: Any) -> str:
    text = str(path or "/").strip()
    if not text.startswith("/"):
        text = f"/{text}"
    segment = text.split("/", 2)[1] if len(text.split("/")) > 1 else "root"
    return _normalize_segment(segment, fallback="root") or "root"


def _build_alignment(
    service_key: str,
    source: str,
    *,
    unmapped: bool,
    reason: str = "",
    candidates: Optional[Iterable[str]] = None,
    confidence: str = "high",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "service_key": service_key,
        "source": source,
        "unmapped": unmapped,
        "reason": reason,
        "confidence": confidence,
        "candidates": [item for item in (candidates or []) if item],
        "context": context or {},
    }


def resolve_host_service_key(host_name: str) -> Dict[str, Any]:
    normalized_host = _normalize_segment(host_name, fallback="local-host") or "local-host"
    return _build_alignment(
        service_key=f"host/{normalized_host}",
        source="host_name",
        unmapped=False,
        candidates=[f"host/{normalized_host}"],
        context={"host_name": normalized_host},
    )


def resolve_docker_service_key(container_name: str, labels: Dict[str, Any] | None = None) -> Dict[str, Any]:
    labels = labels or {}
    compose_project = _normalize_segment(labels.get("com.docker.compose.project"))
    compose_service = _normalize_segment(labels.get("com.docker.compose.service"))
    container_alias = _normalize_segment(container_name, fallback="unknown") or "unknown"

    candidates: List[str] = []
    if compose_project and compose_service:
        candidates.append(f"{compose_project}/{compose_service}")
    if compose_service:
        candidates.append(f"docker/{compose_service}")
    if container_alias:
        candidates.append(f"docker/{container_alias}")

    if compose_project and compose_service:
        return _build_alignment(
            service_key=f"{compose_project}/{compose_service}",
            source="docker_compose",
            unmapped=False,
            candidates=candidates,
            confidence="high",
            context={
                "compose_project": compose_project,
                "compose_service": compose_service,
                "container_name": container_alias,
            },
        )

    if compose_service:
        return _build_alignment(
            service_key=f"docker/{compose_service}",
            source="docker_service_only",
            unmapped=True,
            reason="compose_project_missing",
            candidates=candidates,
            confidence="medium",
            context={
                "compose_service": compose_service,
                "container_name": container_alias,
            },
        )

    return _build_alignment(
        service_key=f"docker/{container_alias}",
        source="container_name_fallback",
        unmapped=True,
        reason="compose_labels_missing",
        candidates=candidates,
        confidence="low",
        context={"container_name": container_alias},
    )


def resolve_log_service_key(host: str = "", path: str = "/", host_hint: str = "") -> Dict[str, Any]:
    normalized_host = _normalize_segment(host)
    normalized_hint = _normalize_segment(host_hint)
    path_prefix = _normalize_path_prefix(path)

    candidates: List[str] = []
    if normalized_host:
        candidates.append(f"{normalized_host}/{path_prefix}")
    if normalized_hint:
        candidates.append(f"{normalized_hint}/{path_prefix}")
    candidates.append(f"unknown/{path_prefix}")

    if normalized_host:
        return _build_alignment(
            service_key=f"{normalized_host}/{path_prefix}",
            source="request_host",
            unmapped=False,
            candidates=candidates,
            confidence="high",
            context={"host": normalized_host, "path_prefix": path_prefix},
        )

    if normalized_hint:
        return _build_alignment(
            service_key=f"{normalized_hint}/{path_prefix}",
            source="log_file_hint",
            unmapped=True,
            reason="request_host_missing",
            candidates=candidates,
            confidence="medium",
            context={"host_hint": normalized_hint, "path_prefix": path_prefix},
        )

    return _build_alignment(
        service_key=f"unknown/{path_prefix}",
        source="path_fallback",
        unmapped=True,
        reason="host_missing",
        candidates=candidates,
        confidence="low",
        context={"path_prefix": path_prefix},
    )


def resolve_explicit_service_key(service_key: str) -> Dict[str, Any]:
    normalized = _normalize_segment(service_key)
    if normalized and "/" in normalized and not normalized.startswith("unknown/"):
        return _build_alignment(
            service_key=normalized,
            source="explicit",
            unmapped=False,
            candidates=[normalized],
            confidence="high",
        )

    fallback = normalized or "unknown/root"
    return _build_alignment(
        service_key=fallback,
        source="explicit_fallback",
        unmapped=True,
        reason="service_key_missing_or_invalid",
        candidates=[fallback],
        confidence="low",
    )


def pick_best_service_key(candidates: Iterable[str], fallback: str = "unknown/root") -> Dict[str, Any]:
    normalized = [
        _normalize_segment(item)
        for item in candidates
        if _normalize_segment(item) and not _normalize_segment(item).startswith("unknown/")
    ]
    if not normalized:
        return _build_alignment(
            service_key=fallback,
            source="candidate_fallback",
            unmapped=True,
            reason="no_valid_candidates",
            candidates=[fallback],
            confidence="low",
        )

    counter = Counter(normalized)
    best_key, _ = counter.most_common(1)[0]
    return _build_alignment(
        service_key=best_key,
        source="candidate_majority",
        unmapped=False,
        candidates=list(counter.keys()),
        confidence="medium",
    )


def merge_alignment(primary: Dict[str, Any], override: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not override:
        return dict(primary)
    merged = dict(primary)
    for key, value in override.items():
        if key == "candidates":
            merged["candidates"] = list(dict.fromkeys([*(primary.get("candidates") or []), *value]))
            continue
        if value not in (None, "", []):
            merged[key] = value
    return merged
