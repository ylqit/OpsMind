"""
建议服务。

根据 incident 输出可读建议和 K8s 草稿。
"""
from __future__ import annotations

import json
import hashlib
from difflib import unified_diff
from typing import Any, Dict, List, Sequence

from pydantic import BaseModel, Field

from engine.capabilities.k8s_yaml_generator import K8sYamlGenerator
from engine.llm.structured_output import run_guarded_structured_chat
from engine.runtime.artifact_store import ArtifactStore
from engine.runtime.models import ArtifactKind, Recommendation, RecommendationKind
from engine.runtime.time_utils import utc_now_iso
from engine.storage.repositories import RecommendationRepository


class RecommendationDraftSchema(BaseModel):
    """建议草稿结构。"""

    observation: str = Field(..., min_length=1, max_length=300)
    recommendation: str = Field(..., min_length=1, max_length=800)
    risk_note: str = Field(..., min_length=1, max_length=300)
    confidence: float = Field(..., ge=0.0, le=1.0)


class RecommendationService:
    """Recommendation 生成服务。"""

    def __init__(self, repository: RecommendationRepository, artifact_store: ArtifactStore):
        self.repository = repository
        self.artifact_store = artifact_store
        self.deployment_generator = K8sYamlGenerator()

    def list_by_incident(self, incident_id: str) -> List[Recommendation]:
        return self.repository.list_by_incident(incident_id)

    async def generate_for_incident(
        self,
        task_id: str,
        incident,
        target_asset_id: str | None = None,
        allowed_kinds: Sequence[str] | None = None,
        llm_router: Any | None = None,
        llm_provider: str | None = None,
        return_guardrail: bool = False,
    ):
        recommendations: List[Recommendation] = []
        guardrail_items: List[dict[str, Any]] = []
        requested_kinds = {item for item in allowed_kinds or []}
        kinds = [kind for kind in self._determine_kinds(incident) if not requested_kinds or kind.value in requested_kinds]
        app_name = incident.service_key.split("/")[-1].replace("_", "-")
        evidence_gate = self._evaluate_incident_evidence(incident)

        for kind in kinds:
            fallback_draft = self._build_fallback_draft(kind, incident, evidence_gate=evidence_gate)
            draft, guardrail_meta = await self._build_guarded_draft(
                incident=incident,
                kind=kind,
                fallback_draft=fallback_draft,
                evidence_gate=evidence_gate,
                llm_router=llm_router,
                llm_provider=llm_provider,
            )
            constrained_draft, risk_rules = self._apply_risk_constraints(kind=kind, incident=incident, draft=draft)
            constrained_draft, evidence_rules = self._apply_evidence_constraints(
                kind=kind,
                incident=incident,
                draft=constrained_draft,
                evidence_gate=evidence_gate,
            )
            all_rules = [*risk_rules, *evidence_rules]
            guardrail_items.append(
                {
                    "kind": kind.value,
                    "risk_rules": all_rules,
                    "evidence_status": evidence_gate["status"],
                    "evidence_signal_count": evidence_gate["signal_count"],
                    **guardrail_meta,
                }
            )

            artifact_refs = []
            if kind == RecommendationKind.MANIFEST_DRAFT and "manifest_requires_evidence" not in evidence_rules:
                artifact_refs.extend(
                    await self._build_manifest_artifacts(
                        task_id=task_id,
                        incident=incident,
                        app_name=app_name,
                        risk_rules=risk_rules,
                    )
                )

            recommendation = Recommendation(
                incident_id=incident.incident_id,
                target_asset_id=target_asset_id,
                kind=kind,
                confidence=float(constrained_draft["confidence"]),
                observation=str(constrained_draft["observation"]),
                recommendation=str(constrained_draft["recommendation"]),
                risk_note=str(constrained_draft["risk_note"]),
                artifact_refs=artifact_refs,
            )
            recommendations.append(self.repository.save(recommendation))

        guardrail_summary = self._build_guardrail_summary(guardrail_items)
        if return_guardrail:
            return recommendations, guardrail_summary
        return recommendations

    async def _build_guarded_draft(
        self,
        incident,
        kind: RecommendationKind,
        fallback_draft: dict[str, Any],
        evidence_gate: dict[str, Any],
        llm_router: Any | None,
        llm_provider: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not llm_router:
            return fallback_draft, {
                "validation_status": "fallback_template",
                "parse_mode": "text_fallback",
                "attempts": 0,
                "retry_count": 0,
                "error_code": "AI_ROUTER_UNAVAILABLE",
                "error_message": "当前未启用可用的 LLM Provider，已使用模板建议",
            }

        messages = [
            {
                "role": "system",
                "content": (
                    "你是资深 SRE 助手。"
                    "请严格输出 JSON 对象，字段固定为："
                    "observation(string), recommendation(string), risk_note(string), confidence(0-1)。"
                    "不要输出 markdown，不要输出额外字段。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"incident_id: {incident.incident_id}\n"
                    f"service_key: {incident.service_key}\n"
                    f"severity: {incident.severity}\n"
                    f"kind: {kind.value}\n"
                    f"incident_summary: {incident.summary}\n"
                    f"reasoning_tags: {', '.join(incident.reasoning_tags) or '-'}\n"
                    f"recommended_actions: {', '.join(incident.recommended_actions) or '-'}\n"
                    f"evidence_status: {evidence_gate['status']}\n"
                    f"evidence_summary: {evidence_gate['summary']}\n"
                    f"fallback_suggestion: {fallback_draft['recommendation']}\n"
                    "若证据不足，请输出保守建议，明确先补采样或补核验，不要直接给出强执行结论。"
                ),
            },
        ]

        result = await run_guarded_structured_chat(
            llm_router=llm_router,
            messages=messages,
            schema_model=RecommendationDraftSchema,
            fallback_payload=fallback_draft,
            provider=llm_provider,
            temperature=0.1,
            max_tokens=420,
            source="recommendation_center",
            endpoint="recommendation_generation",
            max_retries=1,
        )
        return result.data, {
            "validation_status": result.validation_status,
            "parse_mode": result.parse_mode,
            "attempts": result.attempts,
            "retry_count": result.retry_count,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }

    async def _build_manifest_artifacts(
        self,
        task_id: str,
        incident,
        app_name: str,
        risk_rules: list[str],
    ) -> List[Dict[str, Any]]:
        """生成基线草稿、建议草稿、差异结果和稳定化元数据。"""
        baseline_profile = self._build_profile(app_name=app_name, incident=incident, recommended=False)
        recommended_profile = self._build_profile(app_name=app_name, incident=incident, recommended=True)

        baseline_manifest = self._ensure_manifest_stable(
            app_name=app_name,
            profile=baseline_profile,
            rendered_manifest=await self._render_manifest(baseline_profile),
        )
        recommended_manifest = self._ensure_manifest_stable(
            app_name=app_name,
            profile=recommended_profile,
            rendered_manifest=await self._render_manifest(recommended_profile),
        )

        baseline_filename = f"{app_name}-baseline.yaml"
        recommended_filename = f"{app_name}-recommended.yaml"
        diff_filename = f"{app_name}-changes.diff"
        metadata_filename = f"{app_name}-manifest-meta.json"

        diff_content = self._build_manifest_diff(
            baseline_manifest=baseline_manifest,
            recommended_manifest=recommended_manifest,
            baseline_filename=baseline_filename,
            recommended_filename=recommended_filename,
        )

        baseline_artifact = self.artifact_store.write_text(
            task_id=task_id,
            kind=ArtifactKind.MANIFEST,
            content=baseline_manifest,
            filename=baseline_filename,
        )
        recommended_artifact = self.artifact_store.write_text(
            task_id=task_id,
            kind=ArtifactKind.MANIFEST,
            content=recommended_manifest,
            filename=recommended_filename,
        )
        diff_artifact = self.artifact_store.write_text(
            task_id=task_id,
            kind=ArtifactKind.DIFF,
            content=diff_content,
            filename=diff_filename,
        )
        metadata_artifact = self.artifact_store.write_text(
            task_id=task_id,
            kind=ArtifactKind.JSON,
            content=self._build_manifest_metadata(
                baseline_manifest=baseline_manifest,
                recommended_manifest=recommended_manifest,
                diff_content=diff_content,
                baseline_filename=baseline_filename,
                recommended_filename=recommended_filename,
                diff_filename=diff_filename,
                risk_rules=risk_rules,
            ),
            filename=metadata_filename,
        )
        return [
            baseline_artifact.model_dump(mode="json"),
            recommended_artifact.model_dump(mode="json"),
            diff_artifact.model_dump(mode="json"),
            metadata_artifact.model_dump(mode="json"),
        ]

    async def _render_manifest(self, profile: Dict[str, str | int]) -> str:
        generated = await self.deployment_generator.dispatch(**profile)
        if not generated.success:
            return ""
        return generated.data.get("combined", "")

    def _build_profile(self, app_name: str, incident, recommended: bool) -> Dict[str, str | int]:
        default_profile: Dict[str, str | int] = {
            "app_name": app_name,
            "image": "nginx:latest",
            "replicas": 1,
            "port": 80,
            "cpu_request": "100m",
            "memory_request": "128Mi",
            "cpu_limit": "500m",
            "memory_limit": "512Mi",
        }
        if not recommended:
            return default_profile

        tags = set(incident.reasoning_tags)
        profile = dict(default_profile)
        if incident.severity == "critical":
            profile["replicas"] = 2
        if "resource_bottleneck" in tags:
            profile["replicas"] = max(int(profile["replicas"]), 3)
            profile["cpu_request"] = "200m"
            profile["memory_request"] = "256Mi"
            profile["cpu_limit"] = "1000m"
            profile["memory_limit"] = "1Gi"
        if "memory_pressure" in tags:
            profile["memory_request"] = "512Mi"
            profile["memory_limit"] = "2Gi"
        if "traffic_spike" in tags:
            profile["replicas"] = max(int(profile["replicas"]), 4)
        return profile

    def _build_manifest_diff(self, baseline_manifest: str, recommended_manifest: str, baseline_filename: str, recommended_filename: str) -> str:
        diff_lines = list(
            unified_diff(
                baseline_manifest.splitlines(),
                recommended_manifest.splitlines(),
                fromfile=baseline_filename,
                tofile=recommended_filename,
                lineterm="",
            )
        )
        if not diff_lines:
            return "当前建议稿与基线一致，无需调整。\n"
        return "\n".join(diff_lines) + "\n"

    def _ensure_manifest_stable(self, app_name: str, profile: Dict[str, str | int], rendered_manifest: str) -> str:
        """确保 YAML 草稿稳定可读。"""
        content = str(rendered_manifest or "").strip()
        if self._looks_like_manifest(content):
            return f"{content}\n"
        return self._build_stable_manifest_fallback(app_name=app_name, profile=profile)

    def _looks_like_manifest(self, content: str) -> bool:
        if not content:
            return False
        sections = [item.strip() for item in content.split("\n---\n") if item.strip()]
        if not sections:
            return False
        required_tokens = ("apiVersion:", "kind:", "metadata:")
        for section in sections:
            if not all(token in section for token in required_tokens):
                return False
        return True

    def _build_stable_manifest_fallback(self, app_name: str, profile: Dict[str, str | int]) -> str:
        """在生成失败或内容异常时返回稳定的 YAML 草稿。"""
        replicas = int(profile.get("replicas", 1) or 1)
        port = int(profile.get("port", 80) or 80)
        image = str(profile.get("image", "nginx:latest"))
        cpu_request = str(profile.get("cpu_request", "100m"))
        memory_request = str(profile.get("memory_request", "128Mi"))
        cpu_limit = str(profile.get("cpu_limit", "500m"))
        memory_limit = str(profile.get("memory_limit", "512Mi"))

        return (
            f"apiVersion: apps/v1\n"
            f"kind: Deployment\n"
            f"metadata:\n"
            f"  name: {app_name}\n"
            f"  labels:\n"
            f"    app: {app_name}\n"
            f"spec:\n"
            f"  replicas: {replicas}\n"
            f"  selector:\n"
            f"    matchLabels:\n"
            f"      app: {app_name}\n"
            f"  template:\n"
            f"    metadata:\n"
            f"      labels:\n"
            f"        app: {app_name}\n"
            f"    spec:\n"
            f"      containers:\n"
            f"      - name: {app_name}\n"
            f"        image: {image}\n"
            f"        ports:\n"
            f"        - containerPort: {port}\n"
            f"        resources:\n"
            f"          requests:\n"
            f"            cpu: {cpu_request}\n"
            f"            memory: {memory_request}\n"
            f"          limits:\n"
            f"            cpu: {cpu_limit}\n"
            f"            memory: {memory_limit}\n"
            f"---\n"
            f"apiVersion: v1\n"
            f"kind: Service\n"
            f"metadata:\n"
            f"  name: {app_name}\n"
            f"  labels:\n"
            f"    app: {app_name}\n"
            f"spec:\n"
            f"  type: ClusterIP\n"
            f"  selector:\n"
            f"    app: {app_name}\n"
            f"  ports:\n"
            f"  - port: {port}\n"
            f"    targetPort: {port}\n"
            f"    protocol: TCP\n"
        )

    def _build_manifest_metadata(
        self,
        baseline_manifest: str,
        recommended_manifest: str,
        diff_content: str,
        baseline_filename: str,
        recommended_filename: str,
        diff_filename: str,
        risk_rules: list[str],
    ) -> str:
        diff_stats = self._enrich_diff_stats(self._summarize_diff(diff_content))
        baseline_kind_counts = self._extract_manifest_kind_counts(baseline_manifest)
        recommended_kind_counts = self._extract_manifest_kind_counts(recommended_manifest)
        metadata = {
            "schema_version": "v1",
            "generated_at": utc_now_iso(),
            "baseline": {
                "filename": baseline_filename,
                "sha256": self._sha256_text(baseline_manifest),
                "line_count": self._count_non_empty_lines(baseline_manifest),
                "document_count": self._count_manifest_documents(baseline_manifest),
                "resource_types": self._format_resource_types(baseline_kind_counts),
            },
            "recommended": {
                "filename": recommended_filename,
                "sha256": self._sha256_text(recommended_manifest),
                "line_count": self._count_non_empty_lines(recommended_manifest),
                "document_count": self._count_manifest_documents(recommended_manifest),
                "resource_types": self._format_resource_types(recommended_kind_counts),
            },
            "diff": {
                "filename": diff_filename,
                **diff_stats,
            },
            "risk_rules": risk_rules,
            "risk_summary": self._build_manifest_risk_summary(
                diff_stats=diff_stats,
                risk_rules=risk_rules,
                recommended_kind_counts=recommended_kind_counts,
            ),
            "resource_hints": self._build_manifest_resource_hints(
                baseline_kind_counts=baseline_kind_counts,
                recommended_kind_counts=recommended_kind_counts,
            ),
        }
        return json.dumps(metadata, ensure_ascii=False, indent=2)

    def _summarize_diff(self, diff_content: str) -> dict[str, int]:
        added_lines = 0
        removed_lines = 0
        hunk_count = 0
        for line in diff_content.splitlines():
            if line.startswith("@@"):
                hunk_count += 1
                continue
            if line.startswith("+") and not line.startswith("+++"):
                added_lines += 1
                continue
            if line.startswith("-") and not line.startswith("---"):
                removed_lines += 1
        return {
            "added_lines": added_lines,
            "removed_lines": removed_lines,
            "hunk_count": hunk_count,
        }

    def _enrich_diff_stats(self, diff_stats: dict[str, int]) -> dict[str, Any]:
        added_lines = int(diff_stats.get("added_lines") or 0)
        removed_lines = int(diff_stats.get("removed_lines") or 0)
        hunk_count = int(diff_stats.get("hunk_count") or 0)
        total_changed_lines = added_lines + removed_lines
        # 这里使用固定阈值给出变更强度，保证评审信息稳定可解释。
        if total_changed_lines >= 30 or hunk_count >= 6:
            change_level = "high"
        elif total_changed_lines >= 10 or hunk_count >= 3:
            change_level = "medium"
        else:
            change_level = "low"
        return {
            "added_lines": added_lines,
            "removed_lines": removed_lines,
            "hunk_count": hunk_count,
            "total_changed_lines": total_changed_lines,
            "change_level": change_level,
        }

    def _sha256_text(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _count_non_empty_lines(self, content: str) -> int:
        return len([line for line in content.splitlines() if line.strip()])

    def _count_manifest_documents(self, content: str) -> int:
        return len([item for item in content.split("\n---\n") if item.strip()])

    def _extract_manifest_kind_counts(self, content: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("kind:"):
                continue
            _, _, raw_kind = stripped.partition(":")
            kind = raw_kind.strip()
            if not kind:
                continue
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _format_resource_types(self, kind_counts: dict[str, int]) -> list[dict[str, Any]]:
        return [{"kind": key, "count": int(value)} for key, value in sorted(kind_counts.items(), key=lambda item: item[0])]

    def _build_manifest_resource_hints(
        self,
        baseline_kind_counts: dict[str, int],
        recommended_kind_counts: dict[str, int],
    ) -> dict[str, Any]:
        baseline_set = set(baseline_kind_counts.keys())
        recommended_set = set(recommended_kind_counts.keys())
        return {
            "baseline_types": self._format_resource_types(baseline_kind_counts),
            "recommended_types": self._format_resource_types(recommended_kind_counts),
            "added_types": sorted(recommended_set - baseline_set),
            "removed_types": sorted(baseline_set - recommended_set),
        }

    def _build_manifest_risk_summary(
        self,
        diff_stats: dict[str, Any],
        risk_rules: list[str],
        recommended_kind_counts: dict[str, int],
    ) -> dict[str, Any]:
        score = 0
        highlights: list[str] = []

        rule_count = len(risk_rules)
        if rule_count > 0:
            score += min(rule_count, 4)
            highlights.append(f"应用 {rule_count} 条风险约束规则")

        total_changed_lines = int(diff_stats.get("total_changed_lines") or 0)
        if total_changed_lines >= 30:
            score += 3
            highlights.append(f"变更行数较高（{total_changed_lines} 行）")
        elif total_changed_lines >= 10:
            score += 2
            highlights.append(f"变更行数中等（{total_changed_lines} 行）")
        elif total_changed_lines > 0:
            score += 1
            highlights.append(f"变更行数较低（{total_changed_lines} 行）")

        ingress_count = int(recommended_kind_counts.get("Ingress") or 0)
        hpa_count = int(recommended_kind_counts.get("HorizontalPodAutoscaler") or 0)
        if ingress_count > 0:
            score += 1
            highlights.append("涉及 Ingress 路由对象变更")
        if hpa_count > 0:
            score += 1
            highlights.append("涉及 HPA 自动扩缩容对象变更")

        if score >= 6:
            level = "high"
        elif score >= 3:
            level = "medium"
        else:
            level = "low"

        return {
            "level": level,
            "score": score,
            "review_required": True,
            "highlights": highlights[:5],
        }

    def _apply_risk_constraints(
        self,
        kind: RecommendationKind,
        incident,
        draft: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """对建议内容施加风险边界，减少误导性动作。"""
        constrained = dict(draft)
        tags = set(incident.reasoning_tags)
        confidence = float(constrained.get("confidence", 0.6))
        recommendation_text = str(constrained.get("recommendation") or "").strip()
        risk_note = str(constrained.get("risk_note") or "").strip()
        rules: list[str] = []

        if kind == RecommendationKind.SCALE:
            replica_cap = 6 if incident.severity == "critical" else 4
            rules.append(f"scale_replicas_cap_{replica_cap}")
            recommendation_text = self._append_sentence(
                recommendation_text,
                f"扩容建议采用分批发布，副本上限建议不超过 {replica_cap}。",
            )
            risk_note = self._append_sentence(
                risk_note,
                "扩容前先校验上游依赖与核心配置，避免误扩容放大成本。",
            )
            if "upstream_or_config_issue" in tags and "resource_bottleneck" not in tags:
                confidence = min(confidence, 0.55)
                recommendation_text = self._append_sentence(
                    recommendation_text,
                    "当前证据更偏向上游或配置问题，不建议将扩容作为首选动作。",
                )
                rules.append("scale_requires_resource_signal")

        elif kind == RecommendationKind.RATE_LIMIT:
            rules.append("rate_limit_timeboxed_window")
            recommendation_text = self._append_sentence(
                recommendation_text,
                "限流策略建议设置短周期观察窗口，并预置自动回退阈值。",
            )
            risk_note = self._append_sentence(
                risk_note,
                "限流前需确认核心路径白名单，避免误伤登录、支付等关键流量。",
            )
            if "traffic_spike" not in tags:
                confidence = min(confidence, 0.6)
                recommendation_text = self._append_sentence(
                    recommendation_text,
                    "当前未观察到明显流量突增，限流仅建议作为保守兜底措施。",
                )
                rules.append("rate_limit_requires_traffic_spike")

        elif kind == RecommendationKind.RESOURCE_TUNING:
            rules.append("resource_tuning_step_ratio_le_30pct")
            recommendation_text = self._append_sentence(
                recommendation_text,
                "资源调整建议采用小步快跑，单次 requests/limits 调整幅度建议不超过 30%。",
            )
            risk_note = self._append_sentence(
                risk_note,
                "资源参数变更后需持续观察错误率、延迟和重启次数是否同步改善。",
            )
            if "upstream_or_config_issue" in tags and not tags.intersection({"resource_bottleneck", "memory_pressure"}):
                confidence = min(confidence, 0.62)
                recommendation_text = self._append_sentence(
                    recommendation_text,
                    "当前证据更接近上游或配置异常，资源调优不应替代根因排查。",
                )
                rules.append("resource_tuning_secondary_for_upstream_issue")

        elif kind == RecommendationKind.MANIFEST_DRAFT:
            rules.append("manifest_requires_manual_review")
            risk_note = self._append_sentence(
                risk_note,
                "YAML 草稿仅用于评审与演练，应用前必须完成人工复核。",
            )

        constrained["confidence"] = round(max(0.0, min(1.0, confidence)), 2)
        constrained["recommendation"] = recommendation_text
        constrained["risk_note"] = risk_note
        return constrained, rules

    def _evaluate_incident_evidence(self, incident) -> dict[str, Any]:
        """在生成建议前先判断 incident 是否具备足够的现场证据。"""
        counts = {
            "traffic": 0,
            "resource": 0,
            "alert": 0,
            "task": 0,
        }
        for item in incident.evidence_refs:
            if not isinstance(item, dict):
                continue
            layer = str(item.get("layer") or "").strip().lower()
            item_kind = str(item.get("kind") or item.get("type") or "").strip().lower()
            if layer == "traffic" or item_kind == "log":
                counts["traffic"] += 1
                continue
            if layer == "resource" or item_kind == "metric":
                counts["resource"] += 1
                continue
            if layer == "alert" or item_kind == "alert":
                counts["alert"] += 1
                continue
            if layer == "task":
                counts["task"] += 1

        signal_count = counts["traffic"] + counts["resource"] + counts["alert"]
        limitations: list[str] = []
        if counts["traffic"] == 0:
            limitations.append("缺少流量侧样本")
        if counts["resource"] == 0:
            limitations.append("缺少资源侧指标")
        if signal_count == 0:
            limitations.append("缺少可执行的现场信号")

        return {
            "counts": counts,
            "signal_count": signal_count,
            "status": "sufficient" if signal_count >= 2 else "insufficient",
            "summary": (
                f"traffic={counts['traffic']}, resource={counts['resource']}, "
                f"alert={counts['alert']}, task={counts['task']}"
            ),
            "limitations": limitations,
        }

    def _apply_evidence_constraints(
        self,
        kind: RecommendationKind,
        incident,
        draft: dict[str, Any],
        evidence_gate: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """证据不足时统一降级为保守建议，避免输出可直接执行的强结论。"""
        counts = evidence_gate.get("counts") or {}
        traffic_count = int(counts.get("traffic") or 0)
        resource_count = int(counts.get("resource") or 0)
        signal_count = int(evidence_gate.get("signal_count") or 0)

        blocked_rule = ""
        if kind == RecommendationKind.MANIFEST_DRAFT and signal_count < 2:
            blocked_rule = "manifest_requires_evidence"
        elif signal_count == 0:
            blocked_rule = "evidence_required_before_action"
        elif kind == RecommendationKind.RATE_LIMIT and traffic_count == 0:
            blocked_rule = "rate_limit_requires_traffic_evidence"
        elif kind in {RecommendationKind.SCALE, RecommendationKind.RESOURCE_TUNING} and resource_count == 0:
            blocked_rule = "resource_action_requires_resource_evidence"

        if not blocked_rule:
            return draft, []

        if kind == RecommendationKind.SCALE:
            blocked_message = "当前缺少资源侧证据，暂不建议直接扩容。建议先补充 CPU、内存、重启或 OOM 指标，再评估是否需要扩容。"
        elif kind == RecommendationKind.RATE_LIMIT:
            blocked_message = "当前缺少流量侧证据，暂不建议直接限流。建议先补充 5xx 样本、热点路径和状态码分布，再决定是否启用限流。"
        elif kind == RecommendationKind.RESOURCE_TUNING:
            blocked_message = "当前缺少资源侧证据，暂不建议直接调整 requests/limits。建议先补充资源指标与重启记录，再决定是否修改配置。"
        elif kind == RecommendationKind.MANIFEST_DRAFT:
            blocked_message = "当前缺少足够现场证据，暂不建议直接导出执行型 YAML 草稿。建议先补充日志、指标和任务产物，再生成评审草稿。"
        else:
            blocked_message = "当前证据不足，建议先补充现场数据，再决定是否执行变更。"

        constrained = dict(draft)
        constrained["observation"] = self._append_sentence(
            str(constrained.get("observation") or incident.summary or ""),
            "当前仅具备有限证据，以下内容应视为保守提示而非直接执行建议。",
        )
        constrained["recommendation"] = blocked_message
        constrained["risk_note"] = self._append_sentence(
            str(constrained.get("risk_note") or ""),
            "当前建议不能直接作为变更执行依据，需补采样和人工复核后再决定。",
        )
        constrained["confidence"] = min(float(constrained.get("confidence") or 0.5), 0.35)
        return constrained, [blocked_rule]

    def _append_sentence(self, base_text: str, sentence: str) -> str:
        base = str(base_text or "").strip()
        addon = str(sentence or "").strip()
        if not addon:
            return base
        if addon in base:
            return base
        if not base:
            return addon
        if base.endswith(("。", "！", "？", ".", "!", "?")):
            return f"{base}{addon}"
        return f"{base}。{addon}"

    def _determine_kinds(self, incident) -> List[RecommendationKind]:
        tags = set(incident.reasoning_tags)
        results = [RecommendationKind.MANIFEST_DRAFT]
        if "resource_bottleneck" in tags or "memory_pressure" in tags:
            results.append(RecommendationKind.RESOURCE_TUNING)
            results.append(RecommendationKind.SCALE)
        if "traffic_spike" in tags:
            results.append(RecommendationKind.RATE_LIMIT)
        if "upstream_or_config_issue" in tags and RecommendationKind.RESOURCE_TUNING not in results:
            results.append(RecommendationKind.RESOURCE_TUNING)
        return results

    def _build_fallback_draft(self, kind: RecommendationKind, incident, evidence_gate: dict[str, Any] | None = None) -> dict[str, Any]:
        if evidence_gate and evidence_gate.get("status") == "insufficient":
            return {
                "observation": self._append_sentence(incident.summary, "当前现场证据不足，需先补充日志、指标或任务产物。"),
                "recommendation": "证据不足：建议先补采样与补核验，暂不直接执行扩容、限流或资源调优。",
                "risk_note": "当前建议仅用于提示后续排查方向，不能直接作为生产变更依据。",
                "confidence": min(0.35, float(incident.confidence or 0.35)),
            }
        return {
            "observation": incident.summary,
            "recommendation": self._build_recommendation_text(kind, incident),
            "risk_note": "建议稿仅供人工审核，不会自动执行。",
            "confidence": max(0.55, float(incident.confidence)),
        }

    def _build_guardrail_summary(self, guardrail_items: list[dict[str, Any]]) -> dict[str, Any]:
        fallback_count = len([item for item in guardrail_items if item.get("validation_status") == "fallback_template"])
        retried_count = len([item for item in guardrail_items if item.get("validation_status") == "json_retried"])
        schema_error_count = len([item for item in guardrail_items if item.get("error_code") == "AI_OUTPUT_SCHEMA_INVALID"])
        risk_rule_total = sum(len(item.get("risk_rules") or []) for item in guardrail_items)
        risk_rule_covered = len([item for item in guardrail_items if item.get("risk_rules")])
        evidence_blocked_count = len(
            [
                item
                for item in guardrail_items
                if item.get("evidence_status") == "insufficient"
                or "manifest_requires_evidence" in (item.get("risk_rules") or [])
                or "evidence_required_before_action" in (item.get("risk_rules") or [])
            ]
        )
        return {
            "total": len(guardrail_items),
            "fallback_count": fallback_count,
            "retried_count": retried_count,
            "schema_error_count": schema_error_count,
            "risk_rule_total": risk_rule_total,
            "risk_rule_covered": risk_rule_covered,
            "evidence_blocked_count": evidence_blocked_count,
            "has_degraded": fallback_count > 0 or evidence_blocked_count > 0,
            "items": guardrail_items,
        }

    def _build_recommendation_text(self, kind: RecommendationKind, incident) -> str:
        if kind == RecommendationKind.SCALE:
            return "建议优先评估副本数扩容或 HPA 策略，缓解突发流量带来的资源瓶颈。"
        if kind == RecommendationKind.RATE_LIMIT:
            return "建议对入口流量做限流和熔断配置，避免异常来源流量放大影响范围。"
        if kind == RecommendationKind.RESOURCE_TUNING:
            return "建议检查 requests/limits、探针和滚动发布策略，避免配置失衡引发异常。"
        return "已生成基线草稿、建议草稿和差异文件，建议人工审阅后再导出。"
