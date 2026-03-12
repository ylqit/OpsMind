"""
LLM 配置管理模块
支持多 Provider 配置和动态切换
"""
import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class LLMProviderType(str, Enum):
    """LLM Provider 类型"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    QWEN = "qwen"
    CUSTOM = "custom"


class LLMProviderConfig(BaseModel):
    """单个 LLM Provider 配置"""
    name: str = Field(..., description="Provider 名称")
    provider_type: LLMProviderType = Field(..., description="Provider 类型")
    api_key: str = Field(..., description="API Key")
    base_url: Optional[str] = Field(default=None, description="API 基础 URL")
    model: str = Field(..., description="模型名称")
    enabled: bool = Field(default=True, description="是否启用")
    timeout: int = Field(default=30, description="请求超时（秒）")
    max_retries: int = Field(default=2, description="最大重试次数")


class LLMConfig(BaseModel):
    """LLM 总配置"""
    providers: List[LLMProviderConfig] = Field(default=[], description="Provider 列表")
    default_provider: str = Field(default="openai", description="默认 Provider 名称")

    def get_provider(self, name: str) -> Optional[LLMProviderConfig]:
        """获取指定 Provider 配置"""
        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    def get_enabled_providers(self) -> List[LLMProviderConfig]:
        """获取所有启用的 Provider"""
        return [p for p in self.providers if p.enabled]

    def get_default_provider(self) -> Optional[LLMProviderConfig]:
        """获取默认 Provider"""
        return self.get_provider(self.default_provider)


class LLMConfigManager:
    """
    LLM 配置管理器

    管理 LLM Provider 配置，支持：
    - 从配置文件加载
    - 环境变量覆盖
    - 运行时动态修改
    """

    CONFIG_FILE = "llm_config.yaml"

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(".")
        self.config_path = self.config_dir / self.CONFIG_FILE
        self.config: Optional[LLMConfig] = None

    def load_config(self) -> LLMConfig:
        """
        加载 LLM 配置

        优先级：
        1. 配置文件
        2. 环境变量
        3. 默认值
        """
        providers = []
        default_provider = "openai"

        # 1. 从配置文件加载
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    llm_config = file_config.get('llm', {})
                    default_provider = llm_config.get('default_provider', 'openai')

                    for p in llm_config.get('providers', []):
                        provider = LLMProviderConfig(
                            name=p.get('name'),
                            provider_type=LLMProviderType(p.get('type', 'custom')),
                            api_key=p.get('api_key', ''),
                            base_url=p.get('base_url'),
                            model=p.get('model'),
                            enabled=p.get('enabled', True),
                            timeout=p.get('timeout', 30),
                            max_retries=p.get('max_retries', 2)
                        )
                        providers.append(provider)

        # 2. 环境变量覆盖（如果配置中存在对应 Provider）
        # OpenAI
        openai_key = os.getenv('OPENAI_API_KEY')
        if openai_key:
            openai_provider = next((p for p in providers if p.name == 'openai'), None)
            if openai_provider:
                openai_provider.api_key = openai_key
            else:
                providers.append(LLMProviderConfig(
                    name='openai',
                    provider_type=LLMProviderType.OPENAI,
                    api_key=openai_key,
                    base_url=os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1'),
                    model=os.getenv('OPENAI_MODEL', 'gpt-4o'),
                    enabled=True
                ))

        # Anthropic
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        if anthropic_key:
            anthropic_provider = next((p for p in providers if p.name == 'anthropic'), None)
            if anthropic_provider:
                anthropic_provider.api_key = anthropic_key
            else:
                providers.append(LLMProviderConfig(
                    name='anthropic',
                    provider_type=LLMProviderType.ANTHROPIC,
                    api_key=anthropic_key,
                    model=os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-5-20251001'),
                    enabled=True
                ))

        # Qwen（OpenAI 兼容模式）
        qwen_key = os.getenv('QWEN_API_KEY')
        if qwen_key:
            qwen_provider = next((p for p in providers if p.name == 'qwen'), None)
            if qwen_provider:
                qwen_provider.api_key = qwen_key
                if not qwen_provider.base_url:
                    qwen_provider.base_url = os.getenv('QWEN_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
                if not qwen_provider.model:
                    qwen_provider.model = os.getenv('QWEN_MODEL', 'qwen3.5-plus')
            else:
                providers.append(LLMProviderConfig(
                    name='qwen',
                    provider_type=LLMProviderType.QWEN,
                    api_key=qwen_key,
                    base_url=os.getenv('QWEN_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                    model=os.getenv('QWEN_MODEL', 'qwen3.5-plus'),
                    enabled=True
                ))

        # 自定义 LLM
        custom_key = os.getenv('CUSTOM_LLM_API_KEY')
        custom_url = os.getenv('CUSTOM_LLM_BASE_URL')
        if custom_key and custom_url:
            custom_provider = next((p for p in providers if p.name == 'custom'), None)
            if custom_provider:
                custom_provider.api_key = custom_key
                custom_provider.base_url = custom_url
            else:
                providers.append(LLMProviderConfig(
                    name='custom',
                    provider_type=LLMProviderType.CUSTOM,
                    api_key=custom_key,
                    base_url=custom_url,
                    model=os.getenv('CUSTOM_LLM_MODEL', 'custom-model'),
                    enabled=True
                ))

        # 3. 如果没有 Provider，使用默认配置（需要用户自行配置 API Key）
        if not providers:
            providers.append(LLMProviderConfig(
                name='openai',
                provider_type=LLMProviderType.OPENAI,
                api_key='',  # 需要用户配置
                base_url='https://api.openai.com/v1',
                model='gpt-4o',
                enabled=False  # 未配置 API Key 时禁用
            ))

        self.config = LLMConfig(
            providers=providers,
            default_provider=os.getenv('LLM_DEFAULT_PROVIDER', default_provider)
        )
        return self.config

    def save_config(self, config: LLMConfig) -> None:
        """保存配置到文件"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        config_data = {
            'llm': {
                'default_provider': config.default_provider,
                'providers': [
                    {
                        'name': p.name,
                        'type': p.provider_type.value,
                        'api_key': p.api_key,
                        'base_url': p.base_url,
                        'model': p.model,
                        'enabled': p.enabled,
                        'timeout': p.timeout,
                        'max_retries': p.max_retries
                    }
                    for p in config.providers
                ]
            }
        }

        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)

    def update_provider(self, name: str, updates: Dict[str, Any]) -> bool:
        """更新 Provider 配置"""
        if not self.config:
            self.load_config()

        provider = self.config.get_provider(name)
        if provider:
            for key, value in updates.items():
                if hasattr(provider, key):
                    setattr(provider, key, value)
            self.save_config(self.config)
            return True
        return False

    def add_provider(self, provider: LLMProviderConfig) -> bool:
        """添加新的 Provider"""
        if not self.config:
            self.load_config()

        if self.config.get_provider(provider.name):
            return False

        self.config.providers.append(provider)
        self.save_config(self.config)
        return True

    def remove_provider(self, name: str) -> bool:
        """移除 Provider"""
        if not self.config:
            self.load_config()

        for i, p in enumerate(self.config.providers):
            if p.name == name:
                del self.config.providers[i]
                self.save_config(self.config)
                return True
        return False

    def set_default_provider(self, name: str) -> bool:
        """设置默认 Provider"""
        if not self.config:
            self.load_config()

        if self.config.get_provider(name):
            self.config.default_provider = name
            self.save_config(self.config)
            return True
        return False


# 全局配置管理器实例
_llm_config_manager: Optional[LLMConfigManager] = None


def get_llm_config_manager(config_dir: Optional[Path] = None) -> LLMConfigManager:
    """获取 LLM 配置管理器单例"""
    global _llm_config_manager
    if _llm_config_manager is None:
        _llm_config_manager = LLMConfigManager(config_dir)
    return _llm_config_manager
