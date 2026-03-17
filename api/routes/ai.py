"""AI 统一接口。"""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from engine.llm.client import LLMClient
from engine.llm.config import (
    LLMProviderConfig,
    LLMProviderType,
    ensure_default_provider_record,
    resolve_provider_type,
    resolve_provider_base_url,
    serialize_provider_record,
)
from engine.runtime.models import (
    AIProviderConfigRecord,
    AIWritebackKind,
    AIWritebackRecord,
    AnalysisSession,
    AnalysisSessionSource,
    Claim,
    DiagnosisReport,
    TaskType,
)

from .deps import (
    get_ai_call_log_repository_dep,
    get_ai_provider_config_repository_dep,
    get_ai_writeback_repository_dep,
    get_analysis_session_repository_dep,
    get_executor_service_dep,
    get_llm_router_dep,
    get_refresh_llm_router_dep,
    get_task_manager,
)

router = APIRouter(prefix="/ai", tags=["ai"])


class AIChatMessage(BaseModel):
    """聊天消息。"""

    role: Literal["system", "user", "assistant"] = Field(..., description="消息角色")
    content: str = Field(..., min_length=1, description="消息内容")


class AIChatRequest(BaseModel):
    """统一 AI 聊天请求。"""

    messages: list[AIChatMessage] = Field(..., min_length=1, description="消息列表")
    provider: str | None = Field(default=None, description="指定 Provider，可选")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int = Field(default=1000, ge=1, le=8192, description="最大输出 token")
    task_id: str | None = Field(default=None, description="关联任务 ID，可选")


class AIProviderTestRequest(BaseModel):
    """Provider 连通性测试请求。"""

    provider_id: str | None = Field(default=None, description="Provider ID，可选")
    provider_name: str | None = Field(default=None, description="Provider 名称，可选")
    message: str = Field(default="请仅回复 OK", min_length=1, description="测试消息")


class AIProviderCreateRequest(BaseModel):
    """新增 Provider 请求。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, description="Provider 名称")
    provider_type: LLMProviderType = Field(..., alias="type", description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key")
    model: str = Field(..., min_length=1, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool = Field(default=True, description="是否启用")
    is_default: bool | None = Field(default=None, description="是否设为默认")
    timeout: int = Field(default=30, ge=5, le=300, description="超时时间")
    max_retries: int = Field(default=2, ge=0, le=5, description="最大重试次数")


class AIProviderPatchRequest(BaseModel):
    """更新 Provider 请求。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, description="Provider 名称")
    provider_type: LLMProviderType | None = Field(default=None, alias="type", description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key，空字符串表示保持原值")
    model: str | None = Field(default=None, min_length=1, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool | None = Field(default=None, description="是否启用")
    is_default: bool | None = Field(default=None, description="是否设为默认")
    timeout: int | None = Field(default=None, ge=5, le=300, description="超时时间")
    max_retries: int | None = Field(default=None, ge=0, le=5, description="最大重试次数")


class AIAssistantDiagnoseRequest(BaseModel):
    """AI 助手诊断请求。"""

    message: str = Field(..., min_length=1, description="用户输入的问题描述")
    session_id: str | None = Field(default=None, description="分析会话 ID，可选")
    service_key: str | None = Field(default=None, description="服务标识，可选")
    time_range: str | None = Field(default=None, description="时间窗")
    incident_id: str | None = Field(default=None, description="关联异常 ID，可选")
    recommendation_id: str | None = Field(default=None, description="关联建议 ID，可选")
    evidence_ids: list[str] = Field(default_factory=list, description="当前会话证据 ID 列表")
    executor_result_ids: list[str] = Field(default_factory=list, description="执行结果 ID 列表")
    provider: str | None = Field(default=None, description="指定 Provider，可选")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int = Field(default=1200, ge=1, le=8192, description="最大输出 token")
    task_id: str | None = Field(default=None, description="关联任务 ID，可选")
    include_command_packs: bool = Field(default=True, description="是否附带只读命令建议")


class AnalysisSessionUpsertRequest(BaseModel):
    """创建或更新 AI 分析会话。"""

    session_id: str | None = Field(default=None, description="会话 ID，可选")
    source: AnalysisSessionSource = Field(default=AnalysisSessionSource.MANUAL, description="会话来源")
    title: str = Field(default="", description="会话标题")
    prompt: str = Field(default="", description="入口提示词")
    service_key: str = Field(default="", description="服务键")
    time_range: str = Field(default="1h", description="时间窗")
    incident_id: str | None = Field(default=None, description="异常 ID")
    recommendation_id: str | None = Field(default=None, description="建议 ID")
    evidence_ids: list[str] = Field(default_factory=list, description="证据 ID 列表")
    executor_result_ids: list[str] = Field(default_factory=list, description="执行结果 ID 列表")


class AnalysisSessionPatchRequest(BaseModel):
    """增量更新 AI 分析会话。"""

    source: AnalysisSessionSource | None = Field(default=None, description="会话来源")
    title: str | None = Field(default=None, description="会话标题")
    prompt: str | None = Field(default=None, description="入口提示词")
    service_key: str | None = Field(default=None, description="服务键")
    time_range: str | None = Field(default=None, description="时间窗")
    incident_id: str | None = Field(default=None, description="异常 ID")
    recommendation_id: str | None = Field(default=None, description="建议 ID")
    evidence_ids: list[str] | None = Field(default=None, description="证据 ID 列表")
    executor_result_ids: list[str] | None = Field(default=None, description="执行结果 ID 列表")


class AssistantWritebackCreateRequest(BaseModel):
    """保存 AI 助手高价值输出。"""

    session_id: str | None = Field(default=None, description="分析会话 ID，可选")
    kind: AIWritebackKind = Field(..., description="回写类型")
    title: str = Field(default="", description="展示标题")
    summary: str = Field(default="", description="回写摘要")
    content: str = Field(..., min_length=1, description="回写正文")
    provider: str = Field(default="", description="触发回写的模型名称")
    status: str = Field(default="success", description="回写来源状态")
    incident_id: str | None = Field(default=None, description="异常 ID")
    recommendation_id: str | None = Field(default=None, description="建议 ID")
    task_id: str | None = Field(default=None, description="任务 ID，可选")
    claims: list[dict[str, Any]] = Field(default_factory=list, description="结构化结论")
    command_suggestions: list[dict[str, Any]] = Field(default_factory=list, description="只读命令建议")


def _normalize_error_code(error: Exception) -> str:
    text = str(error).lower()
    if "timeout" in text or "timed out" in text:
        return "AI_TIMEOUT"
    if "http" in text and "5" in text:
        return "AI_HTTP_5XX"
    if "http" in text and "4" in text:
        return "AI_HTTP_4XX"
    if "network" in text or "connect" in text:
        return "AI_NETWORK_ERROR"
    return "AI_RUNTIME_ERROR"


def _build_client_from_record(record: AIProviderConfigRecord) -> LLMClient:
    provider_config = LLMProviderConfig(
        name=record.name,
        provider_type=resolve_provider_type(record.provider_type),
        api_key=record.api_key,
        base_url=record.base_url,
        model=record.model,
        enabled=record.enabled,
        timeout=record.timeout,
        max_retries=record.max_retries,
    )
    return LLMClient(provider_config)


def _collect_command_suggestions(executor_service, limit: int = 8) -> list[dict[str, str]]:
    if not executor_service:
        return []
    payload = executor_service.list_readonly_command_packs()
    items = payload.get("items", []) if isinstance(payload, dict) else []
    suggestions: list[dict[str, str]] = []
    for plugin in items:
        plugin_key = str(plugin.get("plugin_key") or "")
        display_name = str(plugin.get("display_name") or plugin_key or "executor")
        command_packs = plugin.get("readonly_command_packs", [])
        if not isinstance(command_packs, list):
            continue
        for pack in command_packs:
            if not isinstance(pack, dict):
                continue
            command = str(pack.get("command") or "").strip()
            if not command:
                continue
            suggestions.append(
                {
                    "plugin_key": plugin_key,
                    "plugin_name": display_name,
                    "category_key": str(pack.get("category_key") or ""),
                    "category_label": str(pack.get("category_label") or ""),
                    "template_id": str(pack.get("template_id") or ""),
                    "title": str(pack.get("title") or command),
                    "description": str(pack.get("description") or ""),
                    "command": command,
                }
            )
            if len(suggestions) >= limit:
                return suggestions
    return suggestions


def _normalize_id_list(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _build_analysis_session_title(
    source: AnalysisSessionSource,
    *,
    service_key: str,
    incident_id: str,
    recommendation_id: str,
) -> str:
    if source == AnalysisSessionSource.RECOMMENDATION and recommendation_id:
        return f"建议诊断 · {recommendation_id}"
    if source == AnalysisSessionSource.INCIDENT and incident_id:
        return f"异常诊断 · {incident_id}"
    if service_key:
        return f"AI 诊断 · {service_key}"
    return "AI 诊断会话"


def _merge_analysis_session_payload(
    current: AnalysisSession | None,
    payload: AnalysisSessionUpsertRequest | AnalysisSessionPatchRequest,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if getattr(payload, "source", None) is not None:
        updates["source"] = payload.source
    if getattr(payload, "title", None) is not None:
        updates["title"] = str(payload.title or "").strip()
    if getattr(payload, "prompt", None) is not None:
        updates["prompt"] = str(payload.prompt or "").strip()
    if getattr(payload, "service_key", None) is not None:
        updates["service_key"] = str(payload.service_key or "").strip()
    if getattr(payload, "time_range", None) is not None:
        updates["time_range"] = str(payload.time_range or "").strip() or "1h"
    if getattr(payload, "incident_id", None) is not None:
        updates["incident_id"] = str(payload.incident_id or "").strip() or None
    if getattr(payload, "recommendation_id", None) is not None:
        updates["recommendation_id"] = str(payload.recommendation_id or "").strip() or None
    if getattr(payload, "evidence_ids", None) is not None:
        updates["evidence_ids"] = _normalize_id_list(payload.evidence_ids)
    if getattr(payload, "executor_result_ids", None) is not None:
        updates["executor_result_ids"] = _normalize_id_list(payload.executor_result_ids)

    source = updates.get("source") or (current.source if current else AnalysisSessionSource.MANUAL)
    service_key = updates.get("service_key") if "service_key" in updates else (current.service_key if current else "")
    incident_id = updates.get("incident_id") if "incident_id" in updates else (current.incident_id if current else "")
    recommendation_id = (
        updates.get("recommendation_id") if "recommendation_id" in updates else (current.recommendation_id if current else "")
    )
    title = updates.get("title")
    if not title:
        updates["title"] = _build_analysis_session_title(
            source,
            service_key=str(service_key or ""),
            incident_id=str(incident_id or ""),
            recommendation_id=str(recommendation_id or ""),
        )
    return updates


def _build_assistant_system_prompt(
    service_key: str,
    time_range: str,
    incident_id: str,
    recommendation_id: str,
    evidence_ids: list[str],
    executor_result_ids: list[str],
    command_suggestions: list[dict[str, str]],
) -> str:
    lines = [
        "你是 opsMind 的运维诊断助手。",
        "请先给出结论，再给出证据与风险，最后给出可执行的下一步。",
        "你只能建议只读诊断动作，不得建议直接执行高风险写操作。",
        (
            f"当前上下文：service_key={service_key or 'all'}，time_range={time_range or '1h'}，"
            f"incident_id={incident_id or 'none'}，recommendation_id={recommendation_id or 'none'}。"
        ),
        f"当前关联证据数：{len(evidence_ids)}，执行结果数：{len(executor_result_ids)}。",
    ]
    if command_suggestions:
        lines.append("可引用的只读命令模板如下：")
        for item in command_suggestions[:5]:
            lines.append(f"- [{item['plugin_name']}] {item['title']}: {item['command']}")
    lines.append(
        "输出格式：\n"
        "1) 诊断结论（2-3 句）\n"
        "2) 证据与风险（列表）\n"
        "3) 下一步动作（仅只读）"
    )
    return "\n".join(lines)


def _build_assistant_fallback_answer(
    reason: str,
    command_suggestions: list[dict[str, str]],
    service_key: str,
    time_range: str,
) -> str:
    lines = [
        "当前 AI Provider 不可用，已切换为本地规则诊断模式。",
        f"建议先聚焦 service_key={service_key or 'all'}，时间窗={time_range or '1h'} 做只读排查。",
    ]
    if command_suggestions:
        lines.append("可先执行以下只读命令：")
        for item in command_suggestions[:3]:
            lines.append(f"- {item['command']}（{item['title']}）")
    else:
        lines.append("当前没有可用命令模板，请先检查执行插件是否已启用。")
    lines.append(f"降级原因：{reason}")
    return "\n".join(lines)


def _trim_text(value: str, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _summarize_writeback_content(content: str) -> str:
    normalized = str(content or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    paragraphs = [item.strip() for item in normalized.split("\n\n") if item.strip()]
    first_block = paragraphs[0] if paragraphs else normalized.splitlines()[0].strip()
    return _trim_text(first_block, limit=180)


def _extract_assistant_summary(answer: str) -> str:
    normalized = str(answer or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    paragraphs = [item.strip() for item in normalized.split("\n\n") if item.strip()]
    if paragraphs:
        return _trim_text(paragraphs[0], limit=220)
    return _trim_text(normalized.splitlines()[0].strip(), limit=220)


def _infer_assistant_risk_level(answer: str, status: str) -> str:
    text = str(answer or "").lower()
    if any(keyword in text for keyword in ["critical", "高风险", "严重", "不可用", "oom", "5xx", "重启风暴"]):
        return "high"
    if status == "degraded":
        return "medium"
    if any(keyword in text for keyword in ["异常", "波动", "延迟", "限流", "告警", "risk"]):
        return "medium"
    return "low"


def _build_assistant_diagnosis_limitations(status: str, evidence_ids: list[str]) -> list[str]:
    limitations: list[str] = []
    if evidence_ids:
        limitations.append("当前会话仅保存证据标识，完整证据内容请回到异常或建议详情查看。")
    else:
        limitations.append("当前会话尚未绑定现场证据，诊断结论主要依赖上下文描述。")
    if status == "degraded":
        limitations.append("当前回答来自降级模式，建议补充可用 Provider 后再次复核。")
    else:
        limitations.append("AI 诊断结论仍需结合现场指标、日志和变更窗口做人工复核。")

    deduplicated: list[str] = []
    for item in limitations:
        if item not in deduplicated:
            deduplicated.append(item)
    return deduplicated[:3]


def _build_assistant_diagnosis_report(
    *,
    answer: str,
    status: str,
    evidence_ids: list[str],
    command_suggestions: list[dict[str, str]],
) -> dict[str, Any]:
    summary = _extract_assistant_summary(answer)
    limitations = _build_assistant_diagnosis_limitations(status, evidence_ids)
    next_actions = [str(item.get("title") or item.get("command") or "").strip() for item in command_suggestions[:4]]
    primary_claim = Claim.model_validate(
        {
            "claim_id": "assistant_diagnosis_summary",
            "kind": "summary",
            "statement": summary or "当前会话暂无可展示的 AI 诊断结论。",
            "evidence_ids": evidence_ids[:3],
            "confidence": 0.38 if status == "degraded" else 0.62,
            "limitations": limitations,
            "title": "AI 诊断结论",
            "source": "ai_assistant",
            "next_step": next_actions[0] if next_actions else None,
        }
    )
    report = DiagnosisReport.model_validate(
        {
            "summary": summary or "当前会话暂无可展示的 AI 诊断结论。",
            "claims": [primary_claim],
            "evidence_refs": [],
            "limitations": limitations,
            "next_actions": [item for item in next_actions if item],
            "risk_level": _infer_assistant_risk_level(answer, status),
        }
    )
    return report.model_dump(mode="python")


def _normalize_command_suggestion_items(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        normalized.append(
            {
                "plugin_key": str(item.get("plugin_key") or "").strip(),
                "plugin_name": str(item.get("plugin_name") or "").strip(),
                "category_key": str(item.get("category_key") or "").strip(),
                "category_label": str(item.get("category_label") or "").strip(),
                "template_id": str(item.get("template_id") or "").strip(),
                "title": str(item.get("title") or command).strip(),
                "description": str(item.get("description") or "").strip(),
                "command": command,
            }
        )
    return normalized


def _build_writeback_title(
    kind: AIWritebackKind,
    *,
    incident_id: str,
    recommendation_id: str,
) -> str:
    if kind == AIWritebackKind.INCIDENT_SUMMARY_DRAFT:
        return f"异常总结草稿 · {incident_id or 'manual'}"
    if kind == AIWritebackKind.RECOMMENDATION_RATIONALE:
        return f"建议说明草稿 · {recommendation_id or incident_id or 'manual'}"
    return f"执行跟进建议 · {recommendation_id or incident_id or 'manual'}"


def _task_matches_incident(task, incident_id: str) -> bool:
    if not incident_id:
        return False
    payload_incident_id = str(task.payload.get("incident_id") or "").strip()
    if payload_incident_id == incident_id:
        return True
    result_ref = task.result_ref if isinstance(task.result_ref, dict) else {}
    return str(result_ref.get("incident_id") or "").strip() == incident_id


def _task_matches_recommendation(task, recommendation_id: str) -> bool:
    if not recommendation_id:
        return False
    payload_recommendation_id = str(task.payload.get("recommendation_id") or "").strip()
    if payload_recommendation_id == recommendation_id:
        return True
    result_ref = task.result_ref if isinstance(task.result_ref, dict) else {}
    if str(result_ref.get("recommendation_id") or "").strip() == recommendation_id:
        return True
    recommendations = result_ref.get("recommendations")
    if not isinstance(recommendations, list):
        return False
    return any(str(item.get("recommendation_id") or "").strip() == recommendation_id for item in recommendations if isinstance(item, dict))


def _infer_related_task_id(task_manager, *, incident_id: str, recommendation_id: str) -> str | None:
    if not task_manager:
        return None

    # 优先把 AI 助手回写挂到最贴近业务对象的任务上，便于任务中心直接回看。
    if recommendation_id:
        tasks = task_manager.list_tasks(task_type=TaskType.RECOMMENDATION_GENERATION.value)
        for task in tasks:
            if _task_matches_recommendation(task, recommendation_id):
                return task.task_id

    if incident_id:
        incident_tasks = task_manager.list_tasks(task_type=TaskType.INCIDENT_ANALYSIS.value)
        for task in incident_tasks:
            if _task_matches_incident(task, incident_id):
                return task.task_id

        recommendation_tasks = task_manager.list_tasks(task_type=TaskType.RECOMMENDATION_GENERATION.value)
        for task in recommendation_tasks:
            if _task_matches_incident(task, incident_id):
                return task.task_id

    return None


def _build_assistant_status_payload(
    llm_router,
    provider_repository,
    executor_service,
) -> dict[str, Any]:
    providers = provider_repository.list() if provider_repository else []
    enabled_items = [item for item in providers if item.enabled]
    default_provider = provider_repository.get_default() if provider_repository else None
    command_suggestions = _collect_command_suggestions(executor_service, limit=10)
    router_clients = getattr(llm_router, "clients", {}) if llm_router else {}
    router_default_provider = str(getattr(llm_router, "default_client_name", "") or "")
    provider_ready = bool(router_clients)

    status: Literal["ready", "degraded", "unavailable"] = "ready"
    status_message = "当前 AI 路由已就绪，可直接进入 AI 诊断链路。"
    degraded_reason = ""
    if not provider_ready and enabled_items:
        status = "degraded"
        status_message = "检测到已启用 Provider，但当前 AI 路由未就绪，页面将降级为只读诊断模式。"
        degraded_reason = status_message
    elif not provider_ready:
        status = "unavailable"
        status_message = "未检测到可用 AI Provider，页面将自动降级为只读诊断模式。"
        degraded_reason = status_message

    default_provider_name = default_provider.name if default_provider else router_default_provider
    default_provider_id = default_provider.provider_id if default_provider else ""
    default_model = default_provider.model if default_provider else ""
    provider_source = "router" if provider_ready else ("repository" if default_provider else "none")

    return {
        "status": status,
        "status_message": status_message,
        "provider_ready": provider_ready,
        "degraded_reason": degraded_reason,
        "default_provider": default_provider_name,
        "default_provider_id": default_provider_id,
        "default_model": default_model,
        "provider_source": provider_source,
        "router_default_provider": router_default_provider,
        "providers_total": len(providers),
        "enabled_providers": len(enabled_items),
        "configured_providers": len([item for item in enabled_items if bool((item.model or "").strip())]),
        "command_suggestions": command_suggestions,
    }


@router.post("/assistant/sessions")
async def create_or_update_analysis_session(
    payload: AnalysisSessionUpsertRequest,
    session_repository=Depends(get_analysis_session_repository_dep),
):
    """创建或更新 AI 助手分析会话。"""
    if not session_repository:
        raise HTTPException(status_code=409, detail="分析会话仓储未初始化")

    current = session_repository.get(payload.session_id) if payload.session_id else None
    if current:
        updates = _merge_analysis_session_payload(current, payload)
        updated = session_repository.update(current.session_id, updates)
        if not updated:
            raise HTTPException(status_code=500, detail="分析会话更新失败")
        return updated.model_dump(mode="json")

    session = AnalysisSession(
        session_id=(payload.session_id or "").strip() or AnalysisSession().session_id,
        source=payload.source,
        title=str(payload.title or "").strip(),
        prompt=str(payload.prompt or "").strip(),
        service_key=str(payload.service_key or "").strip(),
        time_range=str(payload.time_range or "").strip() or "1h",
        incident_id=str(payload.incident_id or "").strip() or None,
        recommendation_id=str(payload.recommendation_id or "").strip() or None,
        evidence_ids=_normalize_id_list(payload.evidence_ids),
        executor_result_ids=_normalize_id_list(payload.executor_result_ids),
    )
    updates = _merge_analysis_session_payload(None, payload)
    session = session.model_copy(update=updates)
    saved = session_repository.save(session)
    return saved.model_dump(mode="json")


@router.get("/assistant/sessions/{session_id}")
async def get_analysis_session(
    session_id: str,
    session_repository=Depends(get_analysis_session_repository_dep),
):
    """读取 AI 助手分析会话。"""
    if not session_repository:
        raise HTTPException(status_code=409, detail="分析会话仓储未初始化")
    session = session_repository.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="分析会话不存在")
    return session.model_dump(mode="json")


@router.patch("/assistant/sessions/{session_id}")
async def patch_analysis_session(
    session_id: str,
    payload: AnalysisSessionPatchRequest,
    session_repository=Depends(get_analysis_session_repository_dep),
):
    """增量更新 AI 助手分析会话。"""
    if not session_repository:
        raise HTTPException(status_code=409, detail="分析会话仓储未初始化")
    current = session_repository.get(session_id)
    if not current:
        raise HTTPException(status_code=404, detail="分析会话不存在")
    updates = _merge_analysis_session_payload(current, payload)
    updated = session_repository.update(session_id, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="分析会话更新失败")
    return updated.model_dump(mode="json")


@router.get("/assistant/status")
async def get_ai_assistant_status(
    llm_router=Depends(get_llm_router_dep),
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    executor_service=Depends(get_executor_service_dep),
):
    """AI 助手工作台状态信息。"""
    return _build_assistant_status_payload(
        llm_router=llm_router,
        provider_repository=provider_repository,
        executor_service=executor_service,
    )


@router.post("/assistant/diagnose")
async def diagnose_with_ai_assistant(
    payload: AIAssistantDiagnoseRequest,
    llm_router=Depends(get_llm_router_dep),
    executor_service=Depends(get_executor_service_dep),
    session_repository=Depends(get_analysis_session_repository_dep),
):
    """对话式只读诊断入口。"""
    started = time.perf_counter()
    session = None
    if payload.session_id and session_repository:
        session = session_repository.get(payload.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="分析会话不存在")

    service_key = (payload.service_key or (session.service_key if session else "") or "").strip()
    time_range = (payload.time_range or (session.time_range if session else "1h") or "1h").strip() or "1h"
    incident_id = (payload.incident_id or (session.incident_id if session else "") or "").strip()
    recommendation_id = (payload.recommendation_id or (session.recommendation_id if session else "") or "").strip()
    evidence_ids = _normalize_id_list(payload.evidence_ids or (session.evidence_ids if session else []))
    executor_result_ids = _normalize_id_list(payload.executor_result_ids or (session.executor_result_ids if session else []))
    command_suggestions = _collect_command_suggestions(executor_service, limit=8) if payload.include_command_packs else []

    if session_repository and session:
        session_repository.update(
            session.session_id,
            {
                "service_key": service_key,
                "time_range": time_range,
                "incident_id": incident_id or None,
                "recommendation_id": recommendation_id or None,
                "evidence_ids": evidence_ids,
                "executor_result_ids": executor_result_ids,
                "prompt": payload.message,
            },
        )

    if payload.provider and llm_router and payload.provider not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    if not llm_router:
        reason = "NO_PROVIDER"
        fallback_answer = _build_assistant_fallback_answer(reason, command_suggestions, service_key, time_range)
        return {
            "status": "degraded",
            "answer": fallback_answer,
            "provider": "",
            "degraded_reason": reason,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "command_suggestions": command_suggestions,
            "diagnosis_report": _build_assistant_diagnosis_report(
                answer=fallback_answer,
                status="degraded",
                evidence_ids=evidence_ids,
                command_suggestions=command_suggestions,
            ),
            "context": {
                "session_id": session.session_id if session else "",
                "service_key": service_key,
                "time_range": time_range,
                "incident_id": incident_id,
                "recommendation_id": recommendation_id,
                "evidence_ids": evidence_ids,
                "executor_result_ids": executor_result_ids,
            },
        }

    system_prompt = _build_assistant_system_prompt(
        service_key=service_key,
        time_range=time_range,
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        evidence_ids=evidence_ids,
        executor_result_ids=executor_result_ids,
        command_suggestions=command_suggestions,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": payload.message},
    ]
    try:
        content = await llm_router.chat(
            messages,
            provider=payload.provider,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            _source="ai_assistant",
            _endpoint="assistant_diagnose",
            _task_id=payload.task_id,
        )
    except Exception as exc:  # noqa: BLE001
        reason = _normalize_error_code(exc)
        fallback_answer = _build_assistant_fallback_answer(reason, command_suggestions, service_key, time_range)
        return {
            "status": "degraded",
            "answer": fallback_answer,
            "provider": payload.provider or getattr(llm_router, "default_client_name", ""),
            "degraded_reason": reason,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "command_suggestions": command_suggestions,
            "diagnosis_report": _build_assistant_diagnosis_report(
                answer=fallback_answer,
                status="degraded",
                evidence_ids=evidence_ids,
                command_suggestions=command_suggestions,
            ),
            "context": {
                "session_id": session.session_id if session else "",
                "service_key": service_key,
                "time_range": time_range,
                "incident_id": incident_id,
                "recommendation_id": recommendation_id,
                "evidence_ids": evidence_ids,
                "executor_result_ids": executor_result_ids,
            },
        }

    return {
        "status": "success",
        "answer": content,
        "provider": payload.provider or llm_router.default_client_name,
        "degraded_reason": "",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "command_suggestions": command_suggestions,
        "diagnosis_report": _build_assistant_diagnosis_report(
            answer=content,
            status="success",
            evidence_ids=evidence_ids,
            command_suggestions=command_suggestions,
        ),
        "context": {
            "session_id": session.session_id if session else "",
            "service_key": service_key,
            "time_range": time_range,
            "incident_id": incident_id,
            "recommendation_id": recommendation_id,
            "evidence_ids": evidence_ids,
            "executor_result_ids": executor_result_ids,
        },
    }


@router.post("/assistant/writebacks")
async def create_assistant_writeback(
    payload: AssistantWritebackCreateRequest,
    session_repository=Depends(get_analysis_session_repository_dep),
    writeback_repository=Depends(get_ai_writeback_repository_dep),
    task_manager=Depends(get_task_manager),
):
    """保存 AI 助手高价值输出，供异常、建议与任务详情复用。"""
    if not writeback_repository:
        raise HTTPException(status_code=409, detail="AI 回写仓储未初始化")

    session = None
    if payload.session_id:
        if not session_repository:
            raise HTTPException(status_code=409, detail="分析会话仓储未初始化")
        session = session_repository.get(payload.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="分析会话不存在")

    incident_id = str(payload.incident_id or (session.incident_id if session else "") or "").strip() or None
    recommendation_id = str(payload.recommendation_id or (session.recommendation_id if session else "") or "").strip() or None
    task_id = str(payload.task_id or "").strip() or _infer_related_task_id(
        task_manager,
        incident_id=incident_id or "",
        recommendation_id=recommendation_id or "",
    )

    if not incident_id and not recommendation_id and not task_id:
        raise HTTPException(status_code=400, detail="AI 回写至少需要关联异常、建议或任务中的一项")

    content = str(payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="AI 回写内容不能为空")

    summary = str(payload.summary or "").strip() or _summarize_writeback_content(content)
    title = str(payload.title or "").strip() or _build_writeback_title(
        payload.kind,
        incident_id=incident_id or "",
        recommendation_id=recommendation_id or "",
    )

    record = AIWritebackRecord(
        session_id=session.session_id if session else (payload.session_id or None),
        kind=payload.kind,
        title=title,
        summary=summary,
        content=content,
        provider=str(payload.provider or "").strip(),
        status=str(payload.status or "success").strip() or "success",
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        task_id=task_id,
        claims=[item for item in payload.claims if isinstance(item, dict)],
        command_suggestions=_normalize_command_suggestion_items(payload.command_suggestions),
    )
    saved = writeback_repository.save(record)
    return {
        "message": "AI 回写已保存",
        "writeback": saved.model_dump(mode="json"),
    }


@router.post("/chat")
async def chat_with_ai(
    payload: AIChatRequest,
    llm_router=Depends(get_llm_router_dep),
):
    """统一聊天入口，支持 Provider 指定、重试与 fallback。"""
    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")
    if payload.provider and payload.provider not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    started = time.perf_counter()
    try:
        content = await llm_router.chat(
            [item.model_dump() for item in payload.messages],
            provider=payload.provider,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            _source="ai_route",
            _endpoint="chat",
            _task_id=payload.task_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": _normalize_error_code(exc),
                "error_message": str(exc),
            },
        ) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": "success",
        "content": content,
        "provider": payload.provider or llm_router.default_client_name,
        "task_id": payload.task_id,
        "latency_ms": latency_ms,
    }


@router.get("/providers")
async def list_ai_providers(provider_repository=Depends(get_ai_provider_config_repository_dep)):
    """读取 Provider 列表。"""
    if not provider_repository:
        return {"providers": [], "default_provider": "", "default_provider_id": ""}

    providers = provider_repository.list()
    default_provider = provider_repository.get_default()
    return {
        "providers": [serialize_provider_record(item) for item in providers],
        "default_provider": default_provider.name if default_provider else "",
        "default_provider_id": default_provider.provider_id if default_provider else "",
    }


@router.get("/call-logs")
async def list_ai_call_logs(
    provider_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
    call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    """读取 AI 调用日志。"""
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status not in {"success", "error"}:
        raise HTTPException(status_code=400, detail="status 仅支持 success 或 error")

    safe_limit = max(1, min(limit, 500))
    if not call_log_repository:
        return {
            "items": [],
            "total": 0,
            "provider_name": provider_name or "",
            "status": normalized_status,
            "limit": safe_limit,
        }

    logs = call_log_repository.list(
        provider_name=provider_name,
        status=normalized_status or None,
        limit=safe_limit,
    )
    return {
        "items": [item.model_dump(mode="json") for item in logs],
        "total": len(logs),
        "provider_name": provider_name or "",
        "status": normalized_status,
        "limit": safe_limit,
    }


@router.post("/providers")
async def create_ai_provider(
    payload: AIProviderCreateRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """新增 Provider 并即时生效。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    normalized_name = payload.name.strip()
    normalized_model = payload.model.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Provider 名称不能为空")
    if not normalized_model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if provider_repository.get_by_name(normalized_name):
        raise HTTPException(status_code=409, detail="Provider 名称已存在")

    default_provider = provider_repository.get_default()
    should_default = payload.is_default if payload.is_default is not None else (default_provider is None and payload.enabled)
    if should_default and not payload.enabled:
        raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")

    record = AIProviderConfigRecord(
        name=normalized_name,
        provider_type=payload.provider_type.value,
        model=normalized_model,
        # 统一按 provider 类型回填默认地址，避免本地兼容服务新建后无可用入口。
        base_url=resolve_provider_base_url(payload.provider_type, payload.base_url),
        api_key=(payload.api_key or "").strip(),
        enabled=payload.enabled,
        is_default=should_default,
        timeout=payload.timeout,
        max_retries=payload.max_retries,
    )
    saved = provider_repository.save(record)

    ensure_default_provider_record(provider_repository)
    refresh_llm_router()

    latest = provider_repository.get(saved.provider_id)
    return {
        "message": "Provider 创建成功",
        "provider": serialize_provider_record(latest or saved),
    }


@router.post("/providers/test")
async def test_ai_provider(
    payload: AIProviderTestRequest,
    llm_router=Depends(get_llm_router_dep),
    provider_repository=Depends(get_ai_provider_config_repository_dep),
):
    """Provider 连通性测试，优先走数据库配置。"""
    started = time.perf_counter()

    target_record = None
    if provider_repository:
        if payload.provider_id:
            target_record = provider_repository.get(payload.provider_id)
        elif payload.provider_name:
            target_record = provider_repository.get_by_name(payload.provider_name)
        else:
            target_record = provider_repository.get_default()

    if target_record:
        try:
            client = _build_client_from_record(target_record)
            content = await client.chat(
                [
                    {"role": "system", "content": "你是连接测试助手，请简短作答。"},
                    {"role": "user", "content": payload.message},
                ],
                temperature=0,
                max_tokens=32,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "provider": target_record.name,
                "error_code": _normalize_error_code(exc),
                "error_message": str(exc),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        return {
            "status": "success",
            "provider": target_record.name,
            "response_preview": content[:120],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")
    if payload.provider_name and payload.provider_name not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    try:
        content = await llm_router.chat(
            [
                {"role": "system", "content": "你是连接测试助手，请简短作答。"},
                {"role": "user", "content": payload.message},
            ],
            provider=payload.provider_name,
            temperature=0,
            max_tokens=32,
            _source="ai_route",
            _endpoint="provider_test",
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "provider": payload.provider_name or llm_router.default_client_name,
            "error_code": _normalize_error_code(exc),
            "error_message": str(exc),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    return {
        "status": "success",
        "provider": payload.provider_name or llm_router.default_client_name,
        "response_preview": content[:120],
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


@router.patch("/providers/{provider_id}")
async def patch_ai_provider(
    provider_id: str,
    payload: AIProviderPatchRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """更新 Provider 配置并热刷新路由。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get(provider_id)
    if not current:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    if payload.is_default is False and current.is_default:
        raise HTTPException(status_code=400, detail="默认 Provider 不能直接取消，请先设置其他默认")
    if payload.enabled is False and current.is_default and payload.is_default is not True:
        raise HTTPException(status_code=400, detail="默认 Provider 不能直接禁用，请先切换默认")

    updates: dict[str, Any] = {}

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Provider 名称不能为空")
        duplicate = provider_repository.get_by_name(new_name)
        if duplicate and duplicate.provider_id != provider_id:
            raise HTTPException(status_code=409, detail="Provider 名称已存在")
        updates["name"] = new_name

    current_provider_type = resolve_provider_type(current.provider_type)
    target_provider_type = payload.provider_type or current_provider_type

    if payload.provider_type is not None:
        updates["provider_type"] = payload.provider_type.value
    if payload.model is not None:
        new_model = payload.model.strip()
        if not new_model:
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        updates["model"] = new_model
    current_base_url = (current.base_url or "").strip() or None
    if payload.base_url is not None:
        candidate_base_url = payload.base_url.strip() or None
        updates["base_url"] = resolve_provider_base_url(target_provider_type, candidate_base_url)
    elif payload.provider_type is not None:
        # 仅切换类型未传 base_url 时，优先将旧类型默认地址替换为新类型默认地址。
        old_default_base_url = resolve_provider_base_url(current_provider_type, None)
        if not current_base_url or current_base_url == old_default_base_url:
            updates["base_url"] = resolve_provider_base_url(target_provider_type, None)
        else:
            updates["base_url"] = resolve_provider_base_url(target_provider_type, current_base_url)
    if payload.enabled is not None:
        updates["enabled"] = payload.enabled
    if payload.timeout is not None:
        updates["timeout"] = payload.timeout
    if payload.max_retries is not None:
        updates["max_retries"] = payload.max_retries
    if payload.api_key is not None and payload.api_key.strip():
        updates["api_key"] = payload.api_key.strip()

    updated = current
    if updates:
        updated = provider_repository.update(provider_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Provider 不存在")

    if payload.is_default is True:
        default_record = provider_repository.set_default(provider_id)
        if not default_record:
            raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")
        updated = default_record

    ensure_default_provider_record(provider_repository)
    refresh_llm_router()

    latest = provider_repository.get(provider_id)
    if not latest:
        raise HTTPException(status_code=500, detail="Provider 更新后读取失败")

    return {
        "message": "Provider 更新成功",
        "provider": serialize_provider_record(latest),
    }


@router.delete("/providers/{provider_id}")
async def delete_ai_provider(
    provider_id: str,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """删除 Provider。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get(provider_id)
    if not current:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if provider_repository.count() <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个 Provider")

    enabled_items = provider_repository.list(enabled_only=True)
    if current.is_default and len(enabled_items) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个启用状态的默认 Provider")

    deleted = provider_repository.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    ensure_default_provider_record(provider_repository)
    refresh_llm_router()
    return {"message": "Provider 删除成功"}
