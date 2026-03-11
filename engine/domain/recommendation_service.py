"""
建议服务。

根据 incident 输出可读建议和 K8s 草稿。
"""
from __future__ import annotations

from typing import List, Sequence

from engine.capabilities.k8s_yaml_generator import K8sYamlGenerator
from engine.runtime.artifact_store import ArtifactStore
from engine.runtime.models import ArtifactKind, Recommendation, RecommendationKind
from engine.storage.repositories import RecommendationRepository


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
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        requested_kinds = {item for item in allowed_kinds or []}
        kinds = [kind for kind in self._determine_kinds(incident) if not requested_kinds or kind.value in requested_kinds]
        app_name = incident.service_key.split("/")[-1].replace("_", "-")

        for kind in kinds:
            observation = incident.summary
            risk_note = "建议稿仅供人工审核，不会自动执行。"
            recommendation_text = self._build_recommendation_text(kind, incident)
            artifact_refs = []

            if kind == RecommendationKind.MANIFEST_DRAFT:
                generated = await self.deployment_generator.dispatch(
                    app_name=app_name,
                    image="nginx:latest",
                    replicas=2 if incident.severity == "critical" else 1,
                    port=80,
                    cpu_request="200m",
                    memory_request="256Mi",
                    cpu_limit="1000m",
                    memory_limit="1Gi",
                )
                manifest = generated.data.get("combined", "") if generated.success else ""
                artifact = self.artifact_store.write_text(
                    task_id=task_id,
                    kind=ArtifactKind.MANIFEST,
                    content=manifest,
                    filename=f"{app_name}-deployment.yaml",
                )
                artifact_refs.append(artifact.model_dump())

            recommendation = Recommendation(
                incident_id=incident.incident_id,
                target_asset_id=target_asset_id,
                kind=kind,
                confidence=max(0.55, float(incident.confidence)),
                observation=observation,
                recommendation=recommendation_text,
                risk_note=risk_note,
                artifact_refs=artifact_refs,
            )
            recommendations.append(self.repository.save(recommendation))
        return recommendations

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

    def _build_recommendation_text(self, kind: RecommendationKind, incident) -> str:
        if kind == RecommendationKind.SCALE:
            return "建议优先评估副本数扩容或 HPA 策略，缓解突发流量带来的资源瓶颈。"
        if kind == RecommendationKind.RATE_LIMIT:
            return "建议对入口流量做限流和熔断配置，避免异常来源流量放大影响范围。"
        if kind == RecommendationKind.RESOURCE_TUNING:
            return "建议检查 requests/limits、探针和滚动发布策略，避免配置失衡引发异常。"
        return "已生成 Deployment/Service 草稿，建议人工审阅后导出。"
