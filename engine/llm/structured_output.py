"""结构化输出守护层。"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ValidationError


class StructuredOutputGuardrailResult(BaseModel):
    """结构化输出守护结果。"""

    data: dict[str, Any]
    validation_status: Literal["json_valid", "json_retried", "fallback_template"]
    parse_mode: Literal["json", "text_fallback"]
    attempts: int = 1
    retry_count: int = 0
    error_code: str = ""
    error_message: str = ""
    raw_preview: str = ""


def extract_json_payload(text: str) -> dict[str, Any] | None:
    """从模型输出提取 JSON，兼容 fenced code block 与纯文本包裹。"""
    normalized = (text or "").strip()
    if not normalized:
        return None

    try:
        parsed = json.loads(normalized)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", normalized)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def run_guarded_structured_chat(
    *,
    llm_router: Any,
    messages: list[dict[str, str]],
    schema_model: type[BaseModel],
    fallback_payload: dict[str, Any],
    provider: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 600,
    source: str = "runtime",
    endpoint: str = "structured_chat",
    max_retries: int = 1,
) -> StructuredOutputGuardrailResult:
    """
    对模型输出执行结构化守护：
    1. Schema 校验
    2. 校验失败自动重试
    3. 最终降级到模板结果
    """
    if not llm_router:
        return StructuredOutputGuardrailResult(
            data=fallback_payload,
            validation_status="fallback_template",
            parse_mode="text_fallback",
            attempts=0,
            retry_count=0,
            error_code="AI_ROUTER_UNAVAILABLE",
            error_message="当前未启用可用的 LLM Provider",
            raw_preview="",
        )

    current_messages = [*messages]
    attempts = 0
    last_error_code = ""
    last_error_message = ""
    last_preview = ""

    for retry_index in range(max_retries + 1):
        attempts += 1
        llm_text = ""
        try:
            llm_text = await llm_router.chat(
                current_messages,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
                _source=source,
                _endpoint=endpoint,
            )
        except Exception as exc:  # noqa: BLE001
            last_error_code = "AI_RUNTIME_ERROR"
            last_error_message = str(exc)
            if retry_index < max_retries:
                continue
            break

        last_preview = (llm_text or "")[:400]
        if not llm_text.strip():
            last_error_code = "AI_EMPTY_RESPONSE"
            last_error_message = "模型返回空内容"
            if retry_index < max_retries:
                continue
            break

        payload = extract_json_payload(llm_text)
        if payload is None:
            last_error_code = "AI_OUTPUT_NOT_JSON"
            last_error_message = "模型输出不是合法 JSON 对象"
            if retry_index < max_retries:
                current_messages = [
                    *messages,
                    {"role": "assistant", "content": llm_text[:1200]},
                    {
                        "role": "user",
                        "content": "请严格仅输出合法 JSON 对象，不要包含 markdown 代码块，也不要输出额外说明。",
                    },
                ]
                continue
            break

        try:
            model = schema_model.model_validate(payload)
        except ValidationError as exc:
            last_error_code = "AI_OUTPUT_SCHEMA_INVALID"
            last_error_message = str(exc).splitlines()[0][:300]
            if retry_index < max_retries:
                current_messages = [
                    *messages,
                    {"role": "assistant", "content": llm_text[:1200]},
                    {
                        "role": "user",
                        "content": (
                            "你输出的 JSON 未通过字段校验，请修复后只输出 JSON。"
                            f"错误摘要：{last_error_message}"
                        ),
                    },
                ]
                continue
            break

        return StructuredOutputGuardrailResult(
            data=model.model_dump(mode="json"),
            validation_status="json_valid" if retry_index == 0 else "json_retried",
            parse_mode="json",
            attempts=attempts,
            retry_count=retry_index,
            error_code="",
            error_message="",
            raw_preview=last_preview,
        )

    return StructuredOutputGuardrailResult(
        data=fallback_payload,
        validation_status="fallback_template",
        parse_mode="text_fallback",
        attempts=attempts,
        retry_count=max(0, attempts - 1),
        error_code=last_error_code or "AI_OUTPUT_GUARDRAIL_FALLBACK",
        error_message=last_error_message or "模型输出未通过校验，已降级为模板结果",
        raw_preview=last_preview,
    )
