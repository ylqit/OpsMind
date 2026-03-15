"""
LLM 配置管理模块
负责 Provider 类型、默认地址、配置加载与序列化。
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from engine.runtime.models import AIProviderConfigRecord


class LLMProviderType(str, Enum):
    """Provider 类型定义。"""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    QWEN = "qwen"
    CUSTOM = "custom"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA = "ollama"
    VLLM = "vllm"
    LOCAL_COMPAT_8998 = "local_8998"


OPENAI_COMPATIBLE_PROVIDER_TYPES = {
    LLMProviderType.OPENAI,
    LLMProviderType.QWEN,
    LLMProviderType.CUSTOM,
    LLMProviderType.OPENAI_COMPATIBLE,
    LLMProviderType.OLLAMA,
    LLMProviderType.VLLM,
    LLMProviderType.LOCAL_COMPAT_8998,
}

LOCAL_OPENAI_COMPATIBLE_PROVIDER_TYPES = {
    LLMProviderType.OPENAI_COMPATIBLE,
    LLMProviderType.OLLAMA,
    LLMProviderType.VLLM,
    LLMProviderType.LOCAL_COMPAT_8998,
}

PROVIDER_DEFAULT_BASE_URLS = {
    LLMProviderType.OPENAI: "https://api.openai.com/v1",
    LLMProviderType.QWEN: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    LLMProviderType.OLLAMA: "http://127.0.0.1:11434/v1",
    LLMProviderType.VLLM: "http://127.0.0.1:8000/v1",
    LLMProviderType.LOCAL_COMPAT_8998: "http://127.0.0.1:8998/v1",
    LLMProviderType.OPENAI_COMPATIBLE: "http://127.0.0.1:8000/v1",
}


def is_openai_compatible_provider_type(provider_type: LLMProviderType) -> bool:
    """判断 Provider 是否遵循 OpenAI 兼容协议。"""
    return provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES


def is_api_key_optional_provider_type(provider_type: LLMProviderType) -> bool:
    """本地兼容服务默认可不配置 API Key。"""
    return provider_type in LOCAL_OPENAI_COMPATIBLE_PROVIDER_TYPES


def resolve_provider_type(provider_type: LLMProviderType | str | None) -> LLMProviderType:
    """把外部输入映射为受支持的类型，未知值回退为通用兼容类型。"""
    if isinstance(provider_type, LLMProviderType):
        return provider_type
    normalized = str(provider_type or "").strip().lower()
    if not normalized:
        return LLMProviderType.CUSTOM
    try:
        return LLMProviderType(normalized)
    except ValueError:
        return LLMProviderType.OPENAI_COMPATIBLE


def resolve_provider_base_url(provider_type: LLMProviderType, base_url: Optional[str]) -> Optional[str]:
    """按类型补全 base_url，显式传值优先。"""
    normalized = (base_url or "").strip()
    if normalized:
        return normalized
    return PROVIDER_DEFAULT_BASE_URLS.get(provider_type)


class LLMProviderConfig(BaseModel):
    """单个 Provider 配置。"""

    name: str = Field(..., description="Provider 名称")
    provider_type: LLMProviderType = Field(..., description="Provider 类型")
    api_key: str = Field(default="", description="API Key")
    base_url: Optional[str] = Field(default=None, description="API 基础 URL")
    model: str = Field(..., description="模型名称")
    enabled: bool = Field(default=True, description="是否启用")
    timeout: int = Field(default=30, description="超时（秒）")
    max_retries: int = Field(default=2, description="最大重试次数")


class LLMConfig(BaseModel):
    """LLM 总配置。"""

    providers: list[LLMProviderConfig] = Field(default_factory=list, description="Provider 列表")
    default_provider: str = Field(default="openai", description="默认 Provider 名称")

    def get_provider(self, name: str) -> Optional[LLMProviderConfig]:
        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    def get_enabled_providers(self) -> list[LLMProviderConfig]:
        return [item for item in self.providers if item.enabled]

    def get_default_provider(self) -> Optional[LLMProviderConfig]:
        return self.get_provider(self.default_provider)


class LLMConfigManager:
    """
    LLM 配置管理器
    支持从文件和环境变量加载 Provider 配置，并可持久化更新。
    """

    CONFIG_FILE = "llm_config.yaml"

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(".")
        self.config_path = self.config_dir / self.CONFIG_FILE
        self.config: Optional[LLMConfig] = None

    def load_config(self) -> LLMConfig:
        providers: list[LLMProviderConfig] = []
        default_provider = "openai"

        # 1) 文件配置
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as file:
                file_config = yaml.safe_load(file) or {}
            llm_config = file_config.get("llm", {})
            default_provider = str(llm_config.get("default_provider") or "openai")
            for item in llm_config.get("providers", []):
                provider_type = resolve_provider_type(item.get("type", "custom"))
                providers.append(
                    LLMProviderConfig(
                        name=str(item.get("name") or "").strip(),
                        provider_type=provider_type,
                        api_key=str(item.get("api_key") or "").strip(),
                        base_url=resolve_provider_base_url(provider_type, item.get("base_url")),
                        model=str(item.get("model") or "").strip(),
                        enabled=bool(item.get("enabled", True)),
                        timeout=int(item.get("timeout", 30)),
                        max_retries=int(item.get("max_retries", 2)),
                    )
                )

        # 2) 环境变量覆盖
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key:
            openai_provider = next((item for item in providers if item.name == "openai"), None)
            if openai_provider:
                openai_provider.api_key = openai_key
            else:
                providers.append(
                    LLMProviderConfig(
                        name="openai",
                        provider_type=LLMProviderType.OPENAI,
                        api_key=openai_key,
                        base_url=resolve_provider_base_url(LLMProviderType.OPENAI, os.getenv("OPENAI_BASE_URL")),
                        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                        enabled=True,
                    )
                )

        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            anthropic_provider = next((item for item in providers if item.name == "anthropic"), None)
            if anthropic_provider:
                anthropic_provider.api_key = anthropic_key
            else:
                providers.append(
                    LLMProviderConfig(
                        name="anthropic",
                        provider_type=LLMProviderType.ANTHROPIC,
                        api_key=anthropic_key,
                        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20251001"),
                        enabled=True,
                    )
                )

        qwen_key = os.getenv("QWEN_API_KEY", "").strip()
        if qwen_key:
            qwen_provider = next((item for item in providers if item.name == "qwen"), None)
            if qwen_provider:
                qwen_provider.api_key = qwen_key
                qwen_provider.base_url = resolve_provider_base_url(
                    LLMProviderType.QWEN,
                    os.getenv("QWEN_BASE_URL") or qwen_provider.base_url,
                )
                if not qwen_provider.model:
                    qwen_provider.model = os.getenv("QWEN_MODEL", "qwen3.5-plus")
            else:
                providers.append(
                    LLMProviderConfig(
                        name="qwen",
                        provider_type=LLMProviderType.QWEN,
                        api_key=qwen_key,
                        base_url=resolve_provider_base_url(LLMProviderType.QWEN, os.getenv("QWEN_BASE_URL")),
                        model=os.getenv("QWEN_MODEL", "qwen3.5-plus"),
                        enabled=True,
                    )
                )

        custom_key = os.getenv("CUSTOM_LLM_API_KEY", "").strip()
        custom_url = os.getenv("CUSTOM_LLM_BASE_URL", "").strip()
        if custom_key and custom_url:
            custom_provider = next((item for item in providers if item.name == "custom"), None)
            if custom_provider:
                custom_provider.api_key = custom_key
                custom_provider.base_url = custom_url
            else:
                providers.append(
                    LLMProviderConfig(
                        name="custom",
                        provider_type=LLMProviderType.CUSTOM,
                        api_key=custom_key,
                        base_url=custom_url,
                        model=os.getenv("CUSTOM_LLM_MODEL", "custom-model"),
                        enabled=True,
                    )
                )

        local_provider_specs = [
            ("ollama", LLMProviderType.OLLAMA, "qwen2.5:7b"),
            ("vllm", LLMProviderType.VLLM, "Qwen/Qwen2.5-7B-Instruct"),
            ("local_8998", LLMProviderType.LOCAL_COMPAT_8998, "local-model"),
        ]
        for provider_name, provider_type, default_model in local_provider_specs:
            env_prefix = provider_name.upper()
            local_base_url = os.getenv(f"{env_prefix}_BASE_URL", "").strip()
            local_model = os.getenv(f"{env_prefix}_MODEL", "").strip()
            local_api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
            if not local_base_url and not local_model and not local_api_key:
                continue

            target_provider = next((item for item in providers if item.name == provider_name), None)
            if target_provider:
                target_provider.provider_type = provider_type
                if local_api_key:
                    target_provider.api_key = local_api_key
                if local_model:
                    target_provider.model = local_model
                target_provider.base_url = resolve_provider_base_url(
                    provider_type,
                    local_base_url or target_provider.base_url,
                )
                continue

            providers.append(
                LLMProviderConfig(
                    name=provider_name,
                    provider_type=provider_type,
                    api_key=local_api_key,
                    base_url=resolve_provider_base_url(provider_type, local_base_url),
                    model=local_model or default_model,
                    enabled=True,
                )
            )

        # 3) 空配置兜底
        if not providers:
            providers.append(
                LLMProviderConfig(
                    name="openai",
                    provider_type=LLMProviderType.OPENAI,
                    api_key="",
                    base_url=resolve_provider_base_url(LLMProviderType.OPENAI, None),
                    model="gpt-4o",
                    enabled=False,
                )
            )

        self.config = LLMConfig(
            providers=providers,
            default_provider=os.getenv("LLM_DEFAULT_PROVIDER", default_provider),
        )
        return self.config

    def save_config(self, config: LLMConfig) -> None:
        """保存配置到文件。"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config_data = {
            "llm": {
                "default_provider": config.default_provider,
                "providers": [
                    {
                        "name": item.name,
                        "type": item.provider_type.value,
                        "api_key": item.api_key,
                        "base_url": item.base_url,
                        "model": item.model,
                        "enabled": item.enabled,
                        "timeout": item.timeout,
                        "max_retries": item.max_retries,
                    }
                    for item in config.providers
                ],
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as file:
            yaml.dump(config_data, file, allow_unicode=True, default_flow_style=False)

    def update_provider(self, name: str, updates: dict[str, Any]) -> bool:
        """更新 Provider 配置。"""
        if not self.config:
            self.load_config()
        provider = self.config.get_provider(name)
        if not provider:
            return False
        for key, value in updates.items():
            if hasattr(provider, key):
                setattr(provider, key, value)
        self.save_config(self.config)
        return True

    def add_provider(self, provider: LLMProviderConfig) -> bool:
        """新增 Provider。"""
        if not self.config:
            self.load_config()
        if self.config.get_provider(provider.name):
            return False
        self.config.providers.append(provider)
        self.save_config(self.config)
        return True

    def remove_provider(self, name: str) -> bool:
        """删除 Provider。"""
        if not self.config:
            self.load_config()
        for index, provider in enumerate(self.config.providers):
            if provider.name == name:
                del self.config.providers[index]
                self.save_config(self.config)
                return True
        return False

    def set_default_provider(self, name: str) -> bool:
        """设置默认 Provider。"""
        if not self.config:
            self.load_config()
        if not self.config.get_provider(name):
            return False
        self.config.default_provider = name
        self.save_config(self.config)
        return True


_llm_config_manager: Optional[LLMConfigManager] = None


def get_llm_config_manager(config_dir: Optional[Path] = None) -> LLMConfigManager:
    """获取 LLM 配置管理器单例。"""
    global _llm_config_manager
    if _llm_config_manager is None:
        _llm_config_manager = LLMConfigManager(config_dir)
    return _llm_config_manager


def serialize_provider_record(record: AIProviderConfigRecord) -> dict[str, Any]:
    """统一 Provider 输出结构。"""
    return {
        "provider_id": record.provider_id,
        "name": record.name,
        "type": record.provider_type,
        "model": record.model,
        "base_url": record.base_url,
        "enabled": record.enabled,
        "is_default": record.is_default,
        "timeout": record.timeout,
        "max_retries": record.max_retries,
        "api_key_configured": bool(record.api_key),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def ensure_default_provider_record(provider_repository) -> AIProviderConfigRecord | None:
    """保证至少存在一个启用态默认 Provider。"""
    if not provider_repository:
        return None

    current_default = provider_repository.get_default()
    if current_default and current_default.enabled:
        return current_default

    enabled_items = provider_repository.list(enabled_only=True)
    if not enabled_items:
        return None

    switched = provider_repository.set_default(enabled_items[0].provider_id)
    return switched or enabled_items[0]

